"""DXF exporter — projects flat 3D solids onto 2D and exports as DXF."""

from pathlib import Path
from typing import Union
import math
import uuid
import time

import cadquery as cq
import ezdxf
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp
from OCP.gp import gp_Pnt, gp_Dir, gp_Ax1, gp_Ax2, gp_Ax3, gp_Trsf, gp_Vec
from OCP.BRep import BRep_Tool
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform

def _find_profile_face(solid: cq.Shape, material_thickness: float) -> cq.Face:
    """Find the best face for the laser-cutting profile.

    Prioritizes faces that are perpendicular to the material thickness dimension.
    If no such face is found (within tolerance), falls back to the largest face.

    Tiebreaker: when two candidate faces have equal area (top and bottom of a flat
    part), prefer the one whose outward normal is most aligned with the positive
    thin-axis direction.  This guarantees the same face is always chosen regardless
    of the order OCC enumerates faces, making the resulting DXF stable across
    machines and OCC versions.
    """
    faces = solid.Faces()
    if not faces:
        raise ValueError("Solid has no faces")

    # Determine the thin axis (the direction perpendicular to the flat face).
    # For a laser-cut part centered at its COM the thin axis is the axis with the
    # smallest bounding-box extent.
    bb = solid.BoundingBox()
    thin_axis_vec: tuple[float, float, float]
    min_dim = min(bb.xlen, bb.ylen, bb.zlen)
    if min_dim == bb.xlen:
        thin_axis_vec = (1.0, 0.0, 0.0)
    elif min_dim == bb.ylen:
        thin_axis_vec = (0.0, 1.0, 0.0)
    else:
        thin_axis_vec = (0.0, 0.0, 1.0)
    tax, tay, taz = thin_axis_vec

    # Optimization: Pre-calculate unique vertex points to avoid redundant OCP calls
    # and to significantly speed up the projection loop.
    unique_points = []
    seen_points = set()
    for v in solid.Vertices():
        p = BRep_Tool.Pnt_s(v.wrapped)
        # Use a coarse grid for de-duplication to handle floating point jitter
        pt = (round(p.X(), 6), round(p.Y(), 6), round(p.Z(), 6))
        if pt not in seen_points:
            unique_points.append(p)
            seen_points.add(pt)

    candidates: list[tuple[cq.Face, float, float]] = []  # (face, area, thin_alignment)

    for face in faces:
        # We only care about planar faces
        surface = BRep_Tool.Surface_s(face.wrapped)
        if surface.DynamicType().Name() != "Geom_Plane":
            continue

        # Get normal directly from the plane definition - much faster than normalAt(Center())
        # surface is already a Geom_Plane if DynamicType().Name() == "Geom_Plane"
        # In OCP, we can just call Pln() on it.
        gp_pln = surface.Pln()
        normal = gp_pln.Position().Direction()

        area = face.Area()
        nx, ny, nz = normal.X(), normal.Y(), normal.Z()

        # Compute the extent of the solid along this normal using pre-calculated points
        min_proj = float('inf')
        max_proj = float('-inf')

        for p in unique_points:
            proj = p.X() * nx + p.Y() * ny + p.Z() * nz
            if proj < min_proj: min_proj = proj
            if proj > max_proj: max_proj = proj

        thickness = max_proj - min_proj
        # Check if this thickness matches the material thickness
        if abs(thickness - material_thickness) < 0.01: # 0.01mm tolerance
            # Alignment with the positive thin-axis direction used as tiebreaker
            alignment = nx * tax + ny * tay + nz * taz
            candidates.append((face, area, alignment))

    if candidates:
        # Primary sort: largest area.  Tiebreaker: face whose normal is most aligned
        # with the positive thin-axis direction (i.e. the "top" face).  This is
        # deterministic regardless of OCC's internal face enumeration order.
        return max(candidates, key=lambda x: (x[1], x[2]))[0]

    # Fallback to absolute largest planar face if no thickness match found,
    # again with the same deterministic tiebreaker.
    planar: list[tuple[cq.Face, float, float]] = []
    for face in faces:
        surface = BRep_Tool.Surface_s(face.wrapped)
        if surface.DynamicType().Name() != "Geom_Plane":
            continue
        gp_pln = surface.Pln()
        normal = gp_pln.Position().Direction()
        alignment = normal.X() * tax + normal.Y() * tay + normal.Z() * taz
        planar.append((face, face.Area(), alignment))
    if planar:
        return max(planar, key=lambda x: (x[1], x[2]))[0]
    return max(faces, key=lambda f: f.Area())


def _face_area(face: cq.Face) -> float:
    """Compute the area of a face."""
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face.wrapped, props)
    return props.Mass()


def _face_normal(face: cq.Face) -> gp_Dir:
    """Get the outward normal of a planar face at its center."""
    # Use CadQuery's built-in normal computation.
    center = face.Center()
    normal = face.normalAt(center)
    return gp_Dir(normal.x, normal.y, normal.z)


def _orient_face_to_xy(solid: cq.Shape, face: cq.Face) -> tuple[cq.Shape, gp_Trsf]:
    """Transform the solid so that the given face lies on the XY plane.

    The face normal is aligned with the Z axis, and the face is then
    rotated around Z to minimize its axis-aligned bounding box area.

    Returns the oriented solid together with the cumulative ``gp_Trsf`` that maps
    the input solid's coordinates into the oriented (XY) frame. The transform is
    needed downstream to project engravings back onto the 3D mesh.
    """
    center = face.Center()
    normal = _face_normal(face)

    # 1. Initial alignment: move center to origin and normal to Z
    source_ax3 = gp_Ax3(gp_Ax2(gp_Pnt(center.x, center.y, center.z), normal))
    target_ax3 = gp_Ax3(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)))

    trsf = gp_Trsf()
    trsf.SetDisplacement(source_ax3, target_ax3)
    builder = BRepBuilderAPI_Transform(solid.wrapped, trsf, True)
    oriented = cq.Shape(builder.Shape())

    # 2. Minimize Bounding Box by rotating around Z
    # We find all linear edges and try aligning them with X or Y axes.
    # To optimize, we only rotate the 2D bounding box of the face, not the whole solid.
    profile_face = _find_profile_face(oriented, 0.0)
    edges = profile_face.Edges()
    
    # Get all points of the face in 2D
    pts_2d = []
    for edge in edges:
        if edge.geomType() == "LINE":
            p1, p2 = edge.startPoint(), edge.endPoint()
            pts_2d.append((p1.x, p1.y))
            pts_2d.append((p2.x, p2.y))
        else:
            # Use a coarser tolerance for orientation search (0.5mm is plenty)
            res = edge.tessellate(0.5)
            e_pts = res[0] if isinstance(res, tuple) else res
            for p in e_pts:
                pts_2d.append((p.X(), p.Y()))
    
    if not pts_2d:
        return oriented, trsf

    # Use a sorted list (not a set) so iteration order is deterministic across
    # Python versions and machines.  When two angles produce the same bounding-box
    # area we keep the first one encountered (smallest angle), which is stable.
    angle_set: set[float] = {0.0}
    for edge in edges:
        if edge.geomType() == "LINE":
            p1 = edge.startPoint()
            p2 = edge.endPoint()
            dx = p2.x - p1.x
            dy = p2.y - p1.y
            if abs(dx) > 1e-6 or abs(dy) > 1e-6:
                angle = math.atan2(dy, dx)
                angle_set.add(angle)

    best_area = float('inf')
    best_angle = 0.0

    for angle in sorted(angle_set):
        cos_a = math.cos(-angle)
        sin_a = math.sin(-angle)

        min_x, max_x = float('inf'), float('-inf')
        min_y, max_y = float('inf'), float('-inf')

        for px, py in pts_2d:
            rx = px * cos_a - py * sin_a
            ry = px * sin_a + py * cos_a
            if rx < min_x: min_x = rx
            if rx > max_x: max_x = rx
            if ry < min_y: min_y = ry
            if ry > max_y: max_y = ry

        area = (max_x - min_x) * (max_y - min_y)
        # Strictly-less-than keeps the first (smallest) angle on ties.
        if area < best_area - 1e-6:
            best_area = area
            best_angle = angle
            
    if abs(best_angle) > 1e-6:
        # Replicate `oriented.rotate((0,0,0),(0,0,1), -degrees(best_angle))` as a
        # gp_Trsf so we can compose it into the cumulative transform. The rotate
        # angle in radians is exactly -best_angle.
        rot = gp_Trsf()
        rot.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), -best_angle)
        oriented = cq.Shape(BRepBuilderAPI_Transform(oriented.wrapped, rot, True).Shape())
        # Multiplied(A) applies A first, then self: rot ∘ trsf.
        return oriented, rot.Multiplied(trsf)
    return oriented, trsf


def _trsf_to_colmajor(trsf: gp_Trsf) -> list[float]:
    """Convert a gp_Trsf to a column-major 4x4 list of 16 floats (Three.js order)."""
    m = [0.0] * 16
    for row in range(1, 4):
        for col in range(1, 5):
            m[(col - 1) * 4 + (row - 1)] = trsf.Value(row, col)
    m[3], m[7], m[11], m[15] = 0.0, 0.0, 0.0, 1.0
    return m


def _mirror_trsf(axis: str) -> gp_Trsf:
    """Reflection across the plane through the origin perpendicular to `axis`."""
    direction = gp_Dir(1, 0, 0)
    if axis == "Y":
        direction = gp_Dir(0, 1, 0)
    elif axis == "Z":
        direction = gp_Dir(0, 0, 1)
    t = gp_Trsf()
    t.SetMirror(gp_Ax2(gp_Pnt(0, 0, 0), direction))
    return t


def export_part_dxf(solid_input: Union[cq.Shape, Path], path: Path, material_thickness: float, kerf_offset_mm: float = 0.0, ref_path: Path = None, flip_h: bool = False, flip_v: bool = False) -> tuple[float, float, float, str, list[float]]:
    """Export the cutting profile of a flat solid as a 2D DXF file.

    Finds the profile face (based on material thickness), orients the solid
    so this face lies on the XY plane, then translates it so its bottom-left
    is at (0,0). Returns ``(width_mm, height_mm, area_mm2, svg_path_string,
    dxf_to_local_matrix)`` where the last element is a column-major 4x4 matrix
    mapping 2D DXF coordinates back into the part's local 3D space (used to place
    engravings onto the 3D mesh in the manual viewer).

    ``flip_h`` / ``flip_v`` mirror the cut profile for paired directional parts
    so the engraving lands on the correct physical face. This is a manufacturing
    concern: the mirror is applied to the exported DXF only, and the returned
    matrix is composed back into the *un-mirrored* source frame so the manual
    viewer keeps showing the part in its true 3D orientation.
    """
    if isinstance(solid_input, Path):
        solid = cq.Shape.importBrep(str(solid_input))
    else:
        solid = solid_input

    # Apply the manufacturing flip (mirror) before generating the cut profile.
    # The thickness axis is the part's thinnest bbox dimension; "horizontal" and
    # "vertical" are the two in-plane axes relative to it.
    flip_trsf = gp_Trsf()  # identity
    if flip_h or flip_v:
        bb = solid.BoundingBox()
        dims = [("X", bb.xlen), ("Y", bb.ylen), ("Z", bb.zlen)]
        thickness_axis = min(dims, key=lambda d: abs(d[1] - material_thickness))[0]
        if thickness_axis == "Z":
            h_axis, v_axis = "X", "Y"
        elif thickness_axis == "X":
            h_axis, v_axis = "Y", "Z"
        else:  # Y
            h_axis, v_axis = "X", "Z"
        if flip_h:
            flip_trsf = _mirror_trsf(h_axis).Multiplied(flip_trsf)
        if flip_v:
            flip_trsf = _mirror_trsf(v_axis).Multiplied(flip_trsf)
        solid = cq.Shape(BRepBuilderAPI_Transform(solid.wrapped, flip_trsf, True).Shape())

    # Find the profile face and orient the part.
    t0 = time.perf_counter()
    profile_face = _find_profile_face(solid, material_thickness)
    oriented, orient_trsf = _orient_face_to_xy(solid, profile_face)
    t_orient = time.perf_counter() - t0

    # After orientation, find the profile face again on the oriented solid.
    oriented_profile = _find_profile_face(oriented, material_thickness)
    original_profile = oriented_profile 
    
    # Apply kerf compensation if requested
    t_kerf = 0.0
    if abs(kerf_offset_mm) > 1e-6:
        t0_k = time.perf_counter()
        try:
            outer = oriented_profile.outerWire()
            inners = oriented_profile.innerWires()
            
            # Offset outer wire OUTWARDS (+kerf_offset_mm)
            # Use kind="intersection" to maintain sharp corners
            new_outer_list = outer.offset2D(kerf_offset_mm, kind="intersection")
            if not new_outer_list:
                raise ValueError("Outer wire offset failed")
            new_outer = new_outer_list[0]
            
            # Offset inner wires INWARDS (-kerf_offset_mm)
            new_inners = []
            for inner in inners:
                try:
                    # Using intersection here as well for stability
                    off_list = inner.offset2D(-kerf_offset_mm, kind="intersection")
                except Exception:
                    # Fallback for circular holes which fail with negative offset in OCP
                    edges = inner.Edges()
                    is_circle = len(edges) == 1 and edges[0].geomType() == "CIRCLE"
                    if is_circle:
                        bb = inner.BoundingBox()
                        center = cq.Vector((bb.xmin + bb.xmax) / 2, (bb.ymin + bb.ymax) / 2, bb.zmin)
                        radius = bb.xlen / 2
                        new_radius = radius - kerf_offset_mm
                        if new_radius > 0:
                            new_wire = cq.Wire.makeCircle(new_radius, center, cq.Vector(0, 0, 1))
                            off_list = [new_wire]
                        else:
                            off_list = []
                    else:
                        raise
                if off_list:
                    new_inners.append(off_list[0])
            
            # Reconstruct the face
            oriented_profile = cq.Face.makeFromWires(new_outer, new_inners)
        except Exception as e:
            raise RuntimeError(f"Kerf compensation failed for part '{path.stem}': {e}") from e
        t_kerf = time.perf_counter() - t0_k

    # Move the profile so its bottom-left is at (0,0)
    face_bb = oriented_profile.BoundingBox()
    oriented_profile = oriented_profile.translate((-face_bb.xmin, -face_bb.ymin, 0))

    # Cumulative (flipped) local-3D -> DXF-2D transform: bottom-left translation ∘ orient.
    # Inverting maps DXF 2D points back onto the flipped solid's local frame, then
    # composing the inverse flip brings them into the ORIGINAL (un-mirrored) source
    # frame — the frame the manual viewer's canonical mesh lives in.
    bl_trsf = gp_Trsf()
    bl_trsf.SetTranslation(gp_Vec(-face_bb.xmin, -face_bb.ymin, 0.0))
    local_to_dxf = bl_trsf.Multiplied(orient_trsf)
    dxf_to_local = _trsf_to_colmajor(flip_trsf.Inverted().Multiplied(local_to_dxf.Inverted()))
    
    # If a reference path is provided, export the UN-OFFSET profile 
    # using the EXACT SAME translation as the offset profile.
    if ref_path:
        ref_profile = original_profile.translate((-face_bb.xmin, -face_bb.ymin, 0))
        ref_wp = cq.Workplane("XY").add(ref_profile)
        ref_path.parent.mkdir(parents=True, exist_ok=True)
        cq.exporters.exportDXF(ref_wp, str(ref_path))

    # Final bounding box for returning dimensions
    final_bb = oriented_profile.BoundingBox()
    width_mm = final_bb.xlen
    height_mm = final_bb.ylen
    
    # Build a Workplane with the face's wires for DXF export.
    t0_e = time.perf_counter()
    wp = cq.Workplane("XY").add(oriented_profile)

    path.parent.mkdir(parents=True, exist_ok=True)
    cq.exporters.exportDXF(wp, str(path))
    t_export = time.perf_counter() - t0_e
    
    # Log individual times if they are significant
    # print(f"    [DEBUG] {path.name}: orient={t_orient:.3f}s, kerf={t_kerf:.3f}s, export={t_export:.3f}s")

    # Fix units in the exported DXF
    try:
        doc = ezdxf.readfile(path)
        doc.header['$INSUNITS'] = 4
        doc.header['$MEASUREMENT'] = 1
        doc.save()
    except Exception as e:
        print(f"Warning: Failed to set DXF units for {path.name}: {e}")
    
    # Generate high-fidelity SVG path string from wires
    svg_paths = []
    
    def get_coords(p):
        if hasattr(p, "x"): return p.x, p.y
        if hasattr(p, "X"): return p.X(), p.Y()
        if isinstance(p, (list, tuple)): return p[0], p[1]
        return 0.0, 0.0

    for wire in oriented_profile.Wires():
        edges = list(wire.Edges())
        if not edges:
            continue
            
        # Reconstruct the wire path by joining edges in order
        ordered_points = []
        current_edges = edges[:]
        
        # Start with the first edge
        first_edge = current_edges.pop(0)
        res_first = first_edge.tessellate(0.1)
        e_pts = res_first[0] if isinstance(res_first, tuple) else res_first
        if not e_pts: e_pts = [first_edge.startPoint(), first_edge.endPoint()]
        ordered_points.extend(e_pts)
        
        while current_edges:
            last_p = ordered_points[-1]
            lx, ly = get_coords(last_p)
            
            found_idx = -1
            reverse_next = False
            
            for i, next_edge in enumerate(current_edges):
                s_next = next_edge.startPoint()
                e_next = next_edge.endPoint()
                sx, sy = get_coords(s_next)
                ex, ey = get_coords(e_next)
                
                # Check if start or end matches our last point
                if abs(sx - lx) < 0.01 and abs(sy - ly) < 0.01:
                    found_idx = i
                    reverse_next = False
                    break
                if abs(ex - lx) < 0.01 and abs(ey - ly) < 0.01:
                    found_idx = i
                    reverse_next = True
                    break
            
            if found_idx == -1:
                break
                
            next_edge = current_edges.pop(found_idx)
            res_next = next_edge.tessellate(0.1)
            next_pts = res_next[0] if isinstance(res_next, tuple) else res_next
            if not next_pts: next_pts = [next_edge.startPoint(), next_edge.endPoint()]
            
            if reverse_next:
                next_pts = next_pts[::-1]
            
            ordered_points.extend(next_pts[1:])
            
        if len(ordered_points) < 2:
            continue
            
        x0, y0 = get_coords(ordered_points[0])
        path_data = f"M {x0:.2f},{y0:.2f}"
        for p in ordered_points[1:]:
            xi, yi = get_coords(p)
            path_data += f" L {xi:.2f},{yi:.2f}"
        path_data += " Z"
        svg_paths.append(path_data)
        
    return width_mm, height_mm, oriented_profile.Area(), " ".join(svg_paths), dxf_to_local


def get_dxf_layer_svg_paths(dxf_path: Path, layer_name: str) -> str:
    """Extract SVG path data for all entities on a specific layer in a DXF file."""
    import ezdxf
    from ezdxf import path
    
    try:
        doc = ezdxf.readfile(dxf_path)
        msp = doc.modelspace()
        entities = msp.query(f'*[layer=="{layer_name}"]')
        
        svg_segments = []
        for entity in entities:
            try:
                # make_path handles LINE, CIRCLE, ARC, LWPOLYLINE, etc.
                p = path.make_path(entity)
                # flattening(0.1) tessellates curves into line segments
                pts = list(p.flattening(distance=0.1))
                if len(pts) < 2:
                    continue
                
                # Format coordinates to 2 decimal places for SVG compactness
                d = f"M {pts[0].x:.2f},{pts[0].y:.2f}"
                for pt in pts[1:]:
                    d += f" L {pt.x:.2f},{pt.y:.2f}"
                svg_segments.append(d)
            except Exception:
                # Skip entities that can't be converted to paths
                continue
                
        return " ".join(svg_segments)
    except Exception:
        return ""
