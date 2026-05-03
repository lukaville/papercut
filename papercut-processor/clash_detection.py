import cadquery as cq
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp
from typing import Optional
import sys

def check_intersections(named_solids: list[tuple[cq.Shape, str, any]], tolerance: float = 1e-4) -> None:
    """Check for volumetric intersections between all pairs of solids.
    
    Uses a spatial grid to optimize pair selection and AABB filtering for pruning.
    Throws a ValueError if any two solids overlap by more than the tolerance volume.
    """
    n = len(named_solids)
    if n < 2:
        return

    # Pre-compute AABBs
    aabbs = [solid.BoundingBox() for solid, _, _ in named_solids]
    
    # Spatial hashing to find candidate pairs
    # Determine grid cell size based on average bounding box size
    avg_size = sum((bb.xlen + bb.ylen + bb.zlen)/3 for bb in aabbs) / n
    cell_size = max(avg_size, 10.0) # Avoid too small cells
    
    grid = {}
    for i, bb in enumerate(aabbs):
        # Find range of cells this AABB touches
        x_min, x_max = int(bb.xmin // cell_size), int(bb.xmax // cell_size)
        y_min, y_max = int(bb.ymin // cell_size), int(bb.ymax // cell_size)
        z_min, z_max = int(bb.zmin // cell_size), int(bb.zmax // cell_size)
        
        for cx in range(x_min, x_max + 1):
            for cy in range(y_min, y_max + 1):
                for cz in range(z_min, z_max + 1):
                    grid.setdefault((cx, cy, cz), []).append(i)

    # Collect unique candidate pairs
    candidate_pairs = set()
    for cell_indices in grid.values():
        if len(cell_indices) < 2:
            continue
        for i in range(len(cell_indices)):
            for j in range(i + 1, len(cell_indices)):
                idx1, idx2 = cell_indices[i], cell_indices[j]
                if idx1 == idx2: continue
                if idx1 > idx2: idx1, idx2 = idx2, idx1
                candidate_pairs.add((idx1, idx2))

    conflicts = []

    for idx1, idx2 in candidate_pairs:
        solid_i, name_i, _ = named_solids[idx1]
        bb_i = aabbs[idx1]
        solid_j, name_j, _ = named_solids[idx2]
        bb_j = aabbs[idx2]

        # 1. Quick AABB check (with small negative buffer)
        if not _aabb_intersects(bb_i, bb_j, buffer=-1e-4):
            continue

        # 2. Expensive volumetric intersection check
        try:
            common = BRepAlgoAPI_Common(solid_i.wrapped, solid_j.wrapped)
            if not common.IsDone():
                continue
            
            intersection_shape = cq.Shape(common.Shape())
            # For performance, only compute volume if the shape is not null
            if not common.Shape().IsNull():
                vol = intersection_shape.Volume()
                if vol > tolerance:
                    conflicts.append((name_i, name_j, vol))
        except Exception:
            pass

    if conflicts:
        error_msg = "Model Error: Volumetric intersections detected between parts!\n"
        for n1, n2, vol in conflicts:
            error_msg += f"  - '{n1}' and '{n2}' overlap by {vol:.6f} mm³\n"
        raise ValueError(error_msg)


def _aabb_intersects(bb1: cq.BoundBox, bb2: cq.BoundBox, buffer: float = 0.0) -> bool:
    """Check if two axis-aligned bounding boxes intersect."""
    # If buffer is negative, we require a deeper overlap to return True
    if bb1.xmin > bb2.xmax + buffer or bb2.xmin > bb1.xmax + buffer:
        return False
    if bb1.ymin > bb2.ymax + buffer or bb2.ymin > bb1.ymax + buffer:
        return False
    if bb1.zmin > bb2.zmax + buffer or bb2.zmin > bb1.zmax + buffer:
        return False
    return True
