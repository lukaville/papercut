"""DXF exporter — projects flat 3D solids onto 2D and exports as DXF."""

from pathlib import Path

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

    The face normal is aligned with the Z axis, and the face center
    is moved to the origin.
    """
    center = face.Center()
    normal = _face_normal(face)

    # Build a coordinate system on the face.
    source_ax3 = gp_Ax3(gp_Ax2(gp_Pnt(center.x, center.y, center.z), normal))
    target_ax3 = gp_Ax3(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)))

    trsf = gp_Trsf()
    trsf.SetDisplacement(source_ax3, target_ax3)

    builder = BRepBuilderAPI_Transform(solid.wrapped, trsf, True)
    return cq.Shape(builder.Shape())


def export_part_dxf(solid: cq.Shape, path: Path, material_thickness: float) -> cq.Shape:
    """Export the cutting profile of a flat solid as a 2D DXF file.

    Finds the profile face (based on material thickness), orients the solid
    so this face lies on the XY plane, then translates it so its bottom-left 
    is at (0,0). Returns the oriented and translated solid.
    """
    # Find the profile face and orient the part.
    profile_face = _find_profile_face(solid, material_thickness)
    oriented = _orient_face_to_xy(solid, profile_face)

    # Move the oriented solid so its bounding box minimum is at (0,0,0)
    # This is crucial for the placement algorithm which assumes bottom-left origin.
    bb = oriented.BoundingBox()
    oriented = oriented.translate((-bb.xmin, -bb.ymin, -bb.zmin))

    # After orientation and translation, the profile face should be at Z ≈ 0 
    # and its bounding box minimum at (0,0).
    oriented_profile = _find_profile_face(oriented, material_thickness)

    # Build a Workplane with the face's wires for DXF export.
    wp = cq.Workplane("XY").add(oriented_profile)

    path.parent.mkdir(parents=True, exist_ok=True)
    cq.exporters.exportDXF(wp, str(path))
    
    return oriented
