"""Manual model exporter.

Produces the 3D data the `manual-builder` web app consumes. The output is
written to ``[project]/manual/model/`` and is fully regenerable from the source
CAD — it is intentionally decoupled from the hand-authored manual content
(steps, view angles, connections) which lives next to it in ``manual.json``.

Robustness strategy (see manual-builder/README.md for the full rationale):

* Parts are keyed by their **3D part name** (the deduplicated, resolved CAD
  name), never by sheet labels like ``A12`` which are reassigned on every run.
* Instances get a **stable id** ``"<partKey>#<ordinal>"`` where the ordinal is
  derived from a coarse, rounded world position so that unrelated edits do not
  renumber existing instances.
* Each part exposes its **topological vertices in canonical (OCC sub-shape)
  order**. The manual references a vertex by its index into that list, which
  survives dimensional changes as long as the part's topology is unchanged.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import cadquery as cq
from OCP.BRep import BRep_Tool
from OCP.TopAbs import TopAbs_VERTEX
from OCP.TopExp import TopExp
from OCP.TopoDS import TopoDS
from OCP.TopTools import TopTools_IndexedMapOfShape

from models import Color, PartGroup, PartInstance, SheetResult

SCHEMA_VERSION = 1

# Tessellation tolerances (mm / rad). Coarse enough for a fast load, fine
# enough for crisp isometric edges.
_MESH_LINEAR_TOL = 0.1
_MESH_ANGULAR_TOL = 0.3

# Rounding (mm) applied to instance world positions when deriving stable
# ordinals. Coarse so small dimensional tweaks keep ordinals stable.
_ORDINAL_POSITION_ROUND_MM = 1.0


@dataclass(frozen=True)
class _Vec3:
    x: float
    y: float
    z: float

    def as_list(self) -> list[float]:
        return [self.x, self.y, self.z]


def _topological_vertices(shape: cq.Shape) -> list[_Vec3]:
    """Return the shape's vertices in canonical OCC sub-shape order.

    ``TopExp.MapShapes_s`` builds an indexed, de-duplicated map of the
    topological vertices. Its ordering is deterministic for a given BREP and is
    the most stable anchor we can offer across parametric regenerations.
    """
    vmap = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape.wrapped, TopAbs_VERTEX, vmap)

    vertices: list[_Vec3] = []
    for i in range(1, vmap.Extent() + 1):
        pnt = BRep_Tool.Pnt_s(TopoDS.Vertex_s(vmap.FindKey(i)))
        vertices.append(_Vec3(pnt.X(), pnt.Y(), pnt.Z()))
    return vertices


def _tessellate(shape: cq.Shape) -> tuple[list[float], list[int]]:
    """Tessellate a shape into a flat (positions, indices) triangle mesh."""
    raw_vertices, triangles = shape.tessellate(_MESH_LINEAR_TOL, _MESH_ANGULAR_TOL)

    positions: list[float] = []
    for v in raw_vertices:
        positions.extend((v.x, v.y, v.z))

    indices: list[int] = []
    for tri in triangles:
        indices.extend(tri)

    return positions, indices


def _bbox(points: list[_Vec3]) -> dict[str, list[float]]:
    xs = [p.x for p in points]
    ys = [p.y for p in points]
    zs = [p.z for p in points]
    return {
        "min": [min(xs), min(ys), min(zs)],
        "max": [max(xs), max(ys), max(zs)],
    }


def _apply_matrix(matrix: list[float], v: _Vec3) -> _Vec3:
    """Apply a column-major 4x4 matrix to a point (w = 1)."""
    m = matrix
    x = m[0] * v.x + m[4] * v.y + m[8] * v.z + m[12]
    y = m[1] * v.x + m[5] * v.y + m[9] * v.z + m[13]
    z = m[2] * v.x + m[6] * v.y + m[10] * v.z + m[14]
    return _Vec3(x, y, z)


def _mat4_mul(a: list[float], b: list[float]) -> list[float]:
    """Multiply two column-major 4x4 matrices: returns a ∘ b (b applied first)."""
    out = [0.0] * 16
    for c in range(4):
        for r in range(4):
            out[c * 4 + r] = sum(a[k * 4 + r] * b[c * 4 + k] for k in range(4))
    return out


def _instance_world_matrix(inst: PartInstance) -> list[float]:
    """Compose the instance placement with its canonical-alignment rotation.

    Rendering uses the group's canonical mesh; ``align_matrix`` rotates that mesh
    into this instance's own orientation before ``matrix`` places it in the world.
    """
    align = getattr(inst, "align_matrix", None)
    if not align:
        return inst.matrix
    return _mat4_mul(inst.matrix, align)


def _part_key_for_group(group: PartGroup, instances: list[PartInstance]) -> str:
    """Resolve the stable part key for a group.

    The main pipeline rewrites ``instance.name`` to the unique, resolved file
    name, so prefer that. Fall back to the group's own names when running before
    name resolution.
    """
    for inst in instances:
        if inst.group_id == group.id:
            return inst.name
    if group.names:
        return sorted(group.names)[0]
    return f"part_{group.id}"


def _sheet_label(inst: PartInstance) -> Optional[str]:
    if inst.sheet_label is None or inst.sheet_part_id is None:
        return None
    return f"{inst.sheet_label}{inst.sheet_part_id}"


def _color_hex(color: Optional[Color]) -> str:
    return color.hex if color else "#bcc4cc"


def export_manual_model(
    project_dir: Path,
    instances: list[PartInstance],
    groups: list[PartGroup],
    sheets: Optional[list[SheetResult]] = None,
    thickness_mm: Optional[float] = None,
    engraving_flip_instances: Optional[dict] = None,
) -> Path:
    """Export the manual 3D model for a project.

    Writes ``manual/model/model.json`` plus one mesh file per unique part to
    ``manual/model/meshes/``. Returns the path to ``model.json``.

    This only touches the ``manual/model/`` subtree; hand-authored manual
    content elsewhere under ``manual/`` is never modified.

    ``engraving_flip_instances`` maps a part key to a set of instance ordinals
    whose engraving side is flipped relative to the part's default side; those
    instances get an explicit ``engravingSide`` in the output.
    """
    engraving_flip_instances = engraving_flip_instances or {}
    model_dir = project_dir / "manual" / "model"
    meshes_dir = model_dir / "meshes"
    meshes_dir.mkdir(parents=True, exist_ok=True)

    # Clear stale mesh files so removed parts do not linger.
    for stale in meshes_dir.glob("*.json"):
        stale.unlink()

    # --- Parts (unique geometries) ---
    parts_json: list[dict] = []
    group_part_key: dict[int, str] = {}
    group_vertices: dict[int, list[_Vec3]] = {}
    part_side_by_key: dict[str, str] = {}  # part key -> default engraving side

    for group in groups:
        part_key = _part_key_for_group(group, instances)
        group_part_key[group.id] = part_key

        vertices = _topological_vertices(group.canonical)
        group_vertices[group.id] = vertices
        positions, indices = _tessellate(group.canonical)

        mesh_name = f"{_safe_filename(part_key)}.json"
        mesh_payload = {
            "schemaVersion": SCHEMA_VERSION,
            "positions": [round(p, 5) for p in positions],
            "indices": indices,
            # Ordered topological vertices — index is the stable reference.
            "vertices": [v.as_list() for v in vertices],
        }
        (meshes_dir / mesh_name).write_text(json.dumps(mesh_payload))

        engraving_entry = None
        if group.engraving:
            part_side_by_key[part_key] = group.engraving.side
            engraving_entry = {
                "side": group.engraving.side,
                "svg": group.engraving.svg,
                "transform": (
                    [round(c, 8) for c in group.engraving.transform]
                    if group.engraving.transform else None
                ),
            }

        parts_json.append({
            "key": part_key,
            "names": sorted(group.names),
            "color": _color_hex(group.color),
            "count": group.count,
            "mesh": f"meshes/{mesh_name}",
            "vertexCount": len(vertices),
            "bbox": _bbox(vertices) if vertices else None,
            "engraving": engraving_entry,
        })

    parts_json.sort(key=lambda p: p["key"])

    # --- Instances (physical placements) ---
    # Group by part key first, then assign deterministic ordinals so unrelated
    # edits do not renumber existing instances.
    by_key: dict[str, list[PartInstance]] = {}
    for inst in instances:
        if inst.group_id is None:
            continue
        key = group_part_key.get(inst.group_id)
        if key is None:
            continue
        by_key.setdefault(key, []).append(inst)

    instances_json: list[dict] = []
    world_points: list[_Vec3] = []

    for key in sorted(by_key):
        members = by_key[key]

        def _ordinal_sort_key(inst: PartInstance) -> tuple:
            m = inst.matrix
            r = _ORDINAL_POSITION_ROUND_MM
            return (
                round(m[12] / r), round(m[13] / r), round(m[14] / r),
                m[12], m[13], m[14],
            )

        flip_ordinals = engraving_flip_instances.get(key, set())
        part_side = part_side_by_key.get(key)

        for ordinal, inst in enumerate(sorted(members, key=_ordinal_sort_key)):
            world_matrix = _instance_world_matrix(inst)
            verts = group_vertices.get(inst.group_id, [])
            world_points.extend(_apply_matrix(world_matrix, v) for v in verts)

            entry = {
                "id": f"{key}#{ordinal}",
                "partKey": key,
                "matrix": [round(c, 8) for c in world_matrix],
                "sheet": _sheet_label(inst),
            }
            # Per-instance side flip (by ordinal), relative to the part's side.
            if part_side and ordinal in flip_ordinals:
                entry["engravingSide"] = "bottom" if part_side == "top" else "top"
            instances_json.append(entry)

    instances_json.sort(key=lambda i: i["id"])

    model = {
        "schemaVersion": SCHEMA_VERSION,
        "project": project_dir.name,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "units": "mm",
        "thickness_mm": thickness_mm,
        "bounds": _bbox(world_points) if world_points else None,
        "parts": parts_json,
        "instances": instances_json,
    }

    model_path = model_dir / "model.json"
    model_path.write_text(json.dumps(model, indent=2))
    return model_path


def _safe_filename(name: str) -> str:
    return "".join(c if (c.isalnum() or c in "-_") else "_" for c in name)
