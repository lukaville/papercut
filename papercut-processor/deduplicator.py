"""Part deduplication — groups identical solids (including mirrors) into equivalence classes."""

from dataclasses import dataclass, field
from typing import Optional, Union

import numpy as np
import cadquery as cq
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp
from OCP.gp import gp_Pnt, gp_Ax1, gp_Ax2, gp_Dir, gp_Trsf
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut


# Relative tolerance for comparing geometric signature values.
_REL_TOL = 1e-3

# Absolute tolerance for near-zero volume checks.
_ABS_TOL = 1e-5


from step_reader import Color

@dataclass
class PartGroup:
    """A group of identical parts (same geometry and color)."""

    canonical: cq.Shape
    """One representative solid from this group."""

    names: set[str] = field(default_factory=set)
    """All names associated with parts in this group."""

    color: Optional[Color] = None
    """The unique color associated with parts in this group."""

    count: int = 0
    """How many instances of this part exist in the model."""


@dataclass
class _ShapeSignature:
    """Rotation/translation-invariant geometric fingerprint of a solid."""

    volume: float
    surface_area: float
    principal_moments: tuple[float, float, float]  # sorted ascending

    def matches(self, other: "_ShapeSignature") -> bool:
        """Check whether two signatures are equal within tolerance."""
        # Optimization: Check volume and area first as they are cheaper/already computed
        for a, b in [(self.volume, other.volume), (self.surface_area, other.surface_area)]:
            if abs(a) < _ABS_TOL and abs(b) < _ABS_TOL:
                continue
            denom = max(abs(a), abs(b))
            if abs(a - b) / (denom or 1.0) > _REL_TOL:
                return False

        # Then check principal moments
        for a, b in zip(self.principal_moments, other.principal_moments):
            if abs(a) < _ABS_TOL and abs(b) < _ABS_TOL:
                continue
            denom = max(abs(a), abs(b))
            if abs(a - b) / (denom or 1.0) > _REL_TOL:
                return False
        return True


def _compute_signature(solid: cq.Shape) -> _ShapeSignature:
    """Compute a rotation/translation-invariant signature for a solid.
    
    Assumes the solid is already centered at its center of mass.
    """
    volume = solid.Volume()
    surface_area = _surface_area(solid)
    principal_moments = _principal_moments(solid)
    return _ShapeSignature(
        volume=volume,
        surface_area=surface_area,
        principal_moments=principal_moments,
    )


def _surface_area(solid: cq.Shape) -> float:
    """Compute total surface area of a solid."""
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(solid.wrapped, props)
    return props.Mass()


def _sorted_bbox_dims(solid: cq.Shape) -> tuple[float, float, float]:
    """Return bounding box dimensions sorted ascending."""
    bb = solid.BoundingBox()
    dims = sorted([bb.xlen, bb.ylen, bb.zlen])
    return (dims[0], dims[1], dims[2])


def _principal_moments(solid: cq.Shape) -> tuple[float, float, float]:
    """Compute sorted principal moments of inertia (eigenvalues of the inertia tensor).

    These are invariant to rotation and translation when computed about the
    center of mass.
    """
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(solid.wrapped, props)

    matrix = props.MatrixOfInertia()
    inertia = np.array([
        [matrix.Value(1, 1), matrix.Value(1, 2), matrix.Value(1, 3)],
        [matrix.Value(2, 1), matrix.Value(2, 2), matrix.Value(2, 3)],
        [matrix.Value(3, 1), matrix.Value(3, 2), matrix.Value(3, 3)],
    ])

    try:
        eigenvalues = np.sort(np.linalg.eigvalsh(inertia))
        return (float(eigenvalues[0]), float(eigenvalues[1]), float(eigenvalues[2]))
    except:
        return (0.0, 0.0, 0.0)


def _center_at_origin(solid: cq.Shape) -> cq.Shape:
    """Translate a solid so its center of mass is at the origin."""
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(solid.wrapped, props)
    com = props.CentreOfMass()

    trsf = gp_Trsf()
    trsf.SetTranslation(gp_Pnt(com.X(), com.Y(), com.Z()), gp_Pnt(0, 0, 0))

    builder = BRepBuilderAPI_Transform(solid.wrapped, trsf, True)
    return cq.Shape(builder.Shape())


def _mirror_solid(solid: cq.Shape, axis: str = "Z") -> cq.Shape:
    """Mirror a solid across a plane perpendicular to the given axis (X, Y, or Z)."""
    trsf = gp_Trsf()
    direction = gp_Dir(0, 0, 1)
    if axis.upper() == "X":
        direction = gp_Dir(1, 0, 0)
    elif axis.upper() == "Y":
        direction = gp_Dir(0, 1, 0)
    
    trsf.SetMirror(gp_Ax2(gp_Pnt(0, 0, 0), direction))
    builder = BRepBuilderAPI_Transform(solid.wrapped, trsf, True)
    return cq.Shape(builder.Shape())


def _is_generic_name(name: str) -> bool:
    """Check if a part name is a generic auto-generated name (e.g. 'Part 1')."""
    import re
    return bool(re.match(r"Part \d+$", name))


def _names_are_compatible(name_a: str, name_b: str) -> bool:
    """Check if two part names are compatible for grouping.
    
    Generic names (e.g. 'Part 1', 'Part 2') are always compatible with anything.
    Two meaningful names are compatible only if they normalize to the same string.
    """
    if _is_generic_name(name_a) or _is_generic_name(name_b):
        return True
    # Normalize: lowercase, replace spaces with underscores
    return name_a.lower().replace(" ", "_") == name_b.lower().replace(" ", "_")


def deduplicate(metadata_solids: list[tuple[cq.Shape, str, Optional[Color]]]) -> list[PartGroup]:
    """Group solids into equivalence classes of identical parts.

    Two parts are considered identical if:
    1. Their geometric signatures match (rotation/translation invariant).
    2. Their colors are identical.
    3. Their names are compatible (same meaningful name, or at least one is generic).
    
    This ensures that parts with different meaningful names (e.g. mirrors
    named 'balcony_side' vs 'balcony_side_left') are kept as separate groups.
    """
    if not metadata_solids:
        return []

    # Pre-compute centered shapes and signatures.
    entries: list[tuple[cq.Shape, _ShapeSignature, cq.Shape, str, Optional[Color]]] = []
    for solid, name, color in metadata_solids:
        centered = _center_at_origin(solid)
        sig = _compute_signature(centered)
        entries.append((solid, sig, centered, name, color))

    groups: list[PartGroup] = []
    # Track which entry indices have been assigned to a group.
    assigned = set()

    for i, (solid_i, sig_i, centered_i, name_i, color_i) in enumerate(entries):
        if i in assigned:
            continue
            
        group = PartGroup(canonical=solid_i, count=1, names={name_i}, color=color_i)
        assigned.add(i)
        
        for j in range(i + 1, len(entries)):
            if j in assigned:
                continue
                
            _, sig_j, _, name_j, color_j = entries[j]
            
            # Match requires geometry, color, AND compatible names
            if (sig_i.matches(sig_j) and color_i == color_j
                    and _names_are_compatible(name_i, name_j)):
                group.count += 1
                group.names.add(name_j)
                assigned.add(j)
                
        groups.append(group)

    return groups
