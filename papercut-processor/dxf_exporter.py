"""DXF exporter — projects flat 3D solids onto 2D and exports as DXF."""

from pathlib import Path
import math

import cadquery as cq
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp
from OCP.gp import gp_Pnt, gp_Dir, gp_Ax2, gp_Ax3, gp_Trsf, gp_Vec
from OCP.BRep import BRep_Tool
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform

def _find_profile_face(solid: cq.Shape, material_thickness: float) -> cq.Face:
    """Find the best face for the laser-cutting profile.
    
    Prioritizes faces that are perpendicular to the material thickness dimension.
    If no such face is found (within tolerance), falls back to the largest face.
    """
    faces = solid.Faces()
    if not faces:
        raise ValueError("Solid has no faces")

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

    candidates: list[tuple[cq.Face, float]] = []
    
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
            candidates.append((face, area))

    if candidates:
        # Return the largest face among candidates that match the thickness
        return max(candidates, key=lambda x: x[1])[0]

    # Fallback to absolute largest face if no thickness match found
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


def _orient_face_to_xy(solid: cq.Shape, face: cq.Face) -> cq.Shape:
    """Transform the solid so that the given face lies on the XY plane.

    The face normal is aligned with the Z axis, and the face is then 
    rotated around Z to minimize its axis-aligned bounding box area.
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
    profile_face = _find_profile_face(oriented, 0.0) # Thickness not needed here
    edges = profile_face.Edges()
    
    candidate_angles = {0.0}
    for edge in edges:
        if edge.geomType() == "LINE":
            p1 = edge.startPoint()
            p2 = edge.endPoint()
            dx = p2.x - p1.x
            dy = p2.y - p1.y
            if abs(dx) > 1e-6 or abs(dy) > 1e-6:
                angle = math.atan2(dy, dx)
                candidate_angles.add(angle)
    
    best_area = float('inf')
    best_shape = oriented
    
    for angle in candidate_angles:
        # Rotate around Z by -angle
        test_shape = oriented.rotate((0,0,0), (0,0,1), -math.degrees(angle))
        bb = test_shape.BoundingBox()
        area = bb.xlen * bb.ylen
        if area < best_area:
            best_area = area
            best_shape = test_shape
            
    return best_shape


def export_part_dxf(solid: cq.Shape, path: Path, material_thickness: float) -> cq.Shape:
    """Export the cutting profile of a flat solid as a 2D DXF file.

    Finds the profile face (based on material thickness), orients the solid
    so this face lies on the XY plane, then translates it so its bottom-left 
    is at (0,0). Returns a tuple of (oriented_solid, profile_area, svg_path_string).
    """
    # Find the profile face and orient the part.
    profile_face = _find_profile_face(solid, material_thickness)
    oriented = _orient_face_to_xy(solid, profile_face)

    # After orientation, find the profile face again on the oriented solid.
    # We want to translate the solid so that THIS face's bounding box starts at (0,0).
    oriented_profile = _find_profile_face(oriented, material_thickness)
    face_bb = oriented_profile.BoundingBox()
    
    # Move the oriented solid so its profile face's bounding box minimum is at (0,0,0)
    # This is crucial for the placement algorithm which assumes bottom-left origin.
    oriented = oriented.translate((-face_bb.xmin, -face_bb.ymin, -face_bb.zmin))
    
    # Update the oriented_profile reference to the translated solid.
    oriented_profile = _find_profile_face(oriented, material_thickness)
    
    # Build a Workplane with the face's wires for DXF export.
    wp = cq.Workplane("XY").add(oriented_profile)

    path.parent.mkdir(parents=True, exist_ok=True)
    cq.exporters.exportDXF(wp, str(path))
    
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
                # Discontinuity in wire, just pick the next one and start a new sub-path
                # but for simplicity we stop here as CadQuery wires should be continuous
                break
                
            next_edge = current_edges.pop(found_idx)
            res_next = next_edge.tessellate(0.1)
            next_pts = res_next[0] if isinstance(res_next, tuple) else res_next
            if not next_pts: next_pts = [next_edge.startPoint(), next_edge.endPoint()]
            
            if reverse_next:
                next_pts = next_pts[::-1]
            
            # Avoid duplicate point at junction
            ordered_points.extend(next_pts[1:])
            
        if len(ordered_points) < 2:
            continue
            
        x0, y0 = get_coords(ordered_points[0])
        path_data = f"M {x0},{y0}"
        for p in ordered_points[1:]:
            xi, yi = get_coords(p)
            path_data += f" L {xi},{yi}"
        path_data += " Z"
        svg_paths.append(path_data)
        
    return oriented, oriented_profile.Area(), " ".join(svg_paths)
