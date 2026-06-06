"""Part deduplication — groups identical solids (including mirrors) into equivalence classes."""

import itertools
from dataclasses import dataclass, field
from typing import Optional, Union

import numpy as np
import cadquery as cq
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp
from OCP.gp import gp_Pnt, gp_Ax1, gp_Ax2, gp_Dir, gp_Trsf
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
from OCP.BRep import BRep_Tool
from OCP.TopAbs import TopAbs_VERTEX
from OCP.TopExp import TopExp
from OCP.TopoDS import TopoDS
from OCP.TopTools import TopTools_IndexedMapOfShape


# Relative tolerance for comparing geometric signature values.
_REL_TOL = 1e-3

# Absolute tolerance for near-zero volume checks.
_ABS_TOL = 1e-5


from models import Color, PartInstance, PartGroup

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
    except Exception as e:
        raise RuntimeError(f"Failed to compute principal moments of inertia: {e}") from e


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


_IDENTITY4 = [
    1.0, 0.0, 0.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, 1.0, 0.0,
    0.0, 0.0, 0.0, 1.0,
]

# The 24 proper rotations among the axis-permutation matrices (the rotational
# symmetries of a cube). Flat laser-cut parts assembled into rectilinear models
# differ only by these axis-aligned rotations, so this set recovers an instance's
# orientation relative to the canonical.
#
# We deliberately exclude the 24 reflections (det = -1): a physical part is never
# mirrored in an assembly, so the true orientation difference is always a proper
# rotation. A negative-determinant transform also reverses triangle winding in
# Three.js, which breaks edge/normal rendering in the viewer. For the symmetric
# flat parts here an equivalent proper rotation always exists (flipping a plate
# over = a 180° in-plane rotation), so restricting to rotations loses nothing.
_PROPER_ROTATIONS: Optional[list[np.ndarray]] = None


def _proper_rotations() -> list[np.ndarray]:
    global _PROPER_ROTATIONS
    if _PROPER_ROTATIONS is None:
        mats = []
        for perm in itertools.permutations(range(3)):
            for signs in itertools.product((1.0, -1.0), repeat=3):
                m = np.zeros((3, 3))
                for row in range(3):
                    m[row, perm[row]] = signs[row]
                if np.linalg.det(m) > 0:  # keep proper rotations only
                    mats.append(m)
        _PROPER_ROTATIONS = mats
    return _PROPER_ROTATIONS


def _solid_vertices(solid: cq.Shape) -> np.ndarray:
    """Return the solid's topological vertices as an (N, 3) array."""
    vmap = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(solid.wrapped, TopAbs_VERTEX, vmap)
    pts = []
    for i in range(1, vmap.Extent() + 1):
        p = BRep_Tool.Pnt_s(TopoDS.Vertex_s(vmap.FindKey(i)))
        pts.append((p.X(), p.Y(), p.Z()))
    return np.array(pts, dtype=float) if pts else np.empty((0, 3))


def _rotation_to_colmajor(rot: np.ndarray) -> list[float]:
    """Convert a 3x3 rotation (maps canonical -> instance) to a column-major 4x4."""
    m = [0.0] * 16
    for c in range(3):
        for r in range(3):
            m[c * 4 + r] = float(rot[r, c])
    m[15] = 1.0
    return m


def _align_rotation(canon_verts: np.ndarray, inst_verts: np.ndarray) -> tuple[list[float], bool]:
    """Find the axis-aligned rotation/reflection mapping canonical -> instance.

    Both vertex sets are centered on their own centroid (the exported matrix
    handles translation). Returns ``(column_major_matrix, ok)``; ``ok`` is False
    when no axis-aligned orientation matches well, in which case identity is
    returned so the instance falls back to the canonical orientation.
    """
    if canon_verts.shape[0] == 0 or inst_verts.shape[0] == 0:
        return list(_IDENTITY4), False

    a = canon_verts - canon_verts.mean(0)
    b = inst_verts - inst_verts.mean(0)
    diag = float(np.linalg.norm(b.max(0) - b.min(0))) or 1.0

    best_rot = None
    best_cost = float("inf")
    for rot in _proper_rotations():
        ra = a @ rot.T
        # Sum of squared distances from each rotated canonical vertex to its
        # nearest instance vertex.
        d2 = ((ra[:, None, :] - b[None, :, :]) ** 2).sum(-1)
        cost = float(d2.min(1).sum())
        if cost < best_cost:
            best_cost = cost
            best_rot = rot

    rms = (best_cost / a.shape[0]) ** 0.5
    if best_rot is None or rms > max(0.1, 0.02 * diag):
        return list(_IDENTITY4), False
    return _rotation_to_colmajor(best_rot), True


def deduplicate(instances: list[PartInstance]) -> list[PartGroup]:
    """Group solids into equivalence classes of identical parts.

    Two parts are considered identical if:
    1. Their geometric signatures match (rotation/translation invariant).
    2. Their colors are identical.
    3. Their names are compatible (same meaningful name, or at least one is generic).
    
    Assigns group_id to each instance and returns the list of PartGroups.
    """
    if not instances:
        return []

    # Pre-compute centered shapes and signatures.
    # We use the solid from the instance, which has local location applied.
    entries: list[tuple[PartInstance, _ShapeSignature, cq.Shape]] = []
    for inst in instances:
        centered = _center_at_origin(inst.solid)
        sig = _compute_signature(centered)
        entries.append((inst, sig, centered))

    groups: list[PartGroup] = []
    # Track which entry indices have been assigned to a group.
    assigned = set()

    for i, (inst_i, sig_i, centered_i) in enumerate(entries):
        if i in assigned:
            continue
            
        group_idx = len(groups)
        group = PartGroup(id=group_idx, canonical=inst_i.solid, count=1, names={inst_i.name}, color=inst_i.color)
        inst_i.group_id = group_idx
        inst_i.align_matrix = list(_IDENTITY4)
        assigned.add(i)

        # Canonical vertices for orientation alignment of the group's members.
        canon_verts = _solid_vertices(centered_i)

        for j in range(i + 1, len(entries)):
            if j in assigned:
                continue

            inst_j, sig_j, centered_j = entries[j]

            # Match requires geometry, color, AND compatible names
            if (sig_i.matches(sig_j) and inst_i.color == inst_j.color
                    and _names_are_compatible(inst_i.name, inst_j.name)):
                group.count += 1
                group.names.add(inst_j.name)
                inst_j.group_id = group_idx
                # The STEP may bake a different orientation into this congruent
                # instance; recover it so the canonical mesh renders correctly.
                align, _ok = _align_rotation(canon_verts, _solid_vertices(centered_j))
                inst_j.align_matrix = align
                assigned.add(j)

        groups.append(group)

    return groups
