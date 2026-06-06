import cadquery as cq
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp
from typing import Optional
import sys

from models import PartInstance
from concurrent.futures import ProcessPoolExecutor
import multiprocessing
from pathlib import Path


def _check_pair(pair_info: tuple[int, int, str, str, str, str, list[float], list[float], tuple[float, ...], tuple[float, ...]], tolerance: float):
    idx1, idx2, name_i, name_j, brep_path_i, brep_path_j, matrix_i, matrix_j, bb_i_raw, bb_j_raw = pair_info
    
    # 1. Quick AABB check
    # bb_raw is (xmin, xmax, ymin, ymax, zmin, zmax)
    if (bb_i_raw[0] > bb_j_raw[1] - 1e-4 or bb_j_raw[0] > bb_i_raw[1] - 1e-4 or
        bb_i_raw[2] > bb_j_raw[3] - 1e-4 or bb_j_raw[2] > bb_i_raw[3] - 1e-4 or
        bb_i_raw[4] > bb_j_raw[5] - 1e-4 or bb_j_raw[4] > bb_i_raw[5] - 1e-4):
        return None

    from OCP.gp import gp_Trsf
    def _list_to_trsf(m: list[float]) -> gp_Trsf:
        trsf = gp_Trsf()
        trsf.SetValues(
            m[0], m[4], m[8],  m[12],
            m[1], m[5], m[9],  m[13],
            m[2], m[6], m[10], m[14]
        )
        return trsf

    # 2. Expensive volumetric intersection check
    try:
        solid_i_raw = cq.Shape.importBrep(brep_path_i)
        solid_j_raw = cq.Shape.importBrep(brep_path_j)
        
        solid_i = solid_i_raw.moved(cq.Location(_list_to_trsf(matrix_i))).wrapped
        solid_j = solid_j_raw.moved(cq.Location(_list_to_trsf(matrix_j))).wrapped
        
        common = BRepAlgoAPI_Common(solid_i, solid_j)
        if not common.IsDone():
            return None
        
        intersection_shape = cq.Shape(common.Shape())
        if not common.Shape().IsNull():
            try:
                vol = intersection_shape.Volume()
                if vol > tolerance:
                    return (name_i, name_j, vol)
            except Exception:
                # Handle cases where Volume() fails on degenerate shapes (like StopIteration)
                pass
    except Exception as e:
        raise RuntimeError(f"Clash detection failed for pair {name_i} and {name_j}: {e}") from e
    return None
    return None




def check_intersections(instances: list[PartInstance], tolerance: float = 1e-4) -> None:
    """Check for volumetric intersections between all pairs of part instances.

    Parts whose name ends with '_extras' are excluded from clash detection —
    they are decorative overlays (stickers, etc.) that may intentionally overlap
    other geometry.  They are still processed by the rest of the pipeline.

    Uses a spatial grid to optimize pair selection and AABB filtering for pruning.
    Throws a ValueError if any two solids overlap by more than the tolerance volume.
    """
    instances = [inst for inst in instances if not inst.name.endswith("_extras")]
    n = len(instances)
    if n < 2:
        return

    from OCP.gp import gp_Trsf

    def _list_to_trsf(m: list[float]) -> gp_Trsf:
        trsf = gp_Trsf()
        trsf.SetValues(
            m[0], m[4], m[8],  m[12],
            m[1], m[5], m[9],  m[13],
            m[2], m[6], m[10], m[14]
        )
        return trsf

    # 1. Pre-compute AABBs in world space
    aabbs = []
    for inst in instances:
        trsf = _list_to_trsf(inst.matrix)
        world_solid = inst.solid.moved(cq.Location(trsf))
        aabbs.append(world_solid.BoundingBox())
    
    # Spatial hashing to find candidate pairs
    avg_size = sum((bb.xlen + bb.ylen + bb.zlen)/3 for bb in aabbs) / n
    cell_size = max(avg_size, 10.0)
    
    grid = {}
    for i, bb in enumerate(aabbs):
        x_min, x_max = int(bb.xmin // cell_size), int(bb.xmax // cell_size)
        y_min, y_max = int(bb.ymin // cell_size), int(bb.ymax // cell_size)
        z_min, z_max = int(bb.zmin // cell_size), int(bb.zmax // cell_size)
        
        for cx in range(x_min, x_max + 1):
            for cy in range(y_min, y_max + 1):
                for cz in range(z_min, z_max + 1):
                    grid.setdefault((cx, cy, cz), []).append(i)

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

    # Pre-export solids to BREP for stable multiprocessing
    # Use a temporary cache directory
    brep_cache_dir = Path(".cache/clash_breps")
    brep_cache_dir.mkdir(parents=True, exist_ok=True)
    
    instance_breps = []
    for i, inst in enumerate(instances):
        brep_path = brep_cache_dir / f"inst_{i}.brep"
        # Always export for now to be safe, or check for changes
        inst.solid.exportBrep(str(brep_path))
        instance_breps.append(str(brep_path))

    # Prepare data for parallel processing
    tasks = []
    for idx1, idx2 in candidate_pairs:
        bb_i = aabbs[idx1]
        bb_j = aabbs[idx2]
        
        # Convert AABBs to picklable tuples (xmin, xmax, ymin, ymax, zmin, zmax)
        bb_i_raw = (bb_i.xmin, bb_i.xmax, bb_i.ymin, bb_i.ymax, bb_i.zmin, bb_i.zmax)
        bb_j_raw = (bb_j.xmin, bb_j.xmax, bb_j.ymin, bb_j.ymax, bb_j.zmin, bb_j.zmax)
        
        inst_i = instances[idx1]
        inst_j = instances[idx2]
        
        tasks.append((
            idx1, idx2, 
            inst_i.name, inst_j.name, 
            instance_breps[idx1], instance_breps[idx2],
            inst_i.matrix, inst_j.matrix,
            bb_i_raw, bb_j_raw
        ))

    conflicts = []
    
    # Use ProcessPoolExecutor for parallel volumetric checks
    with ProcessPoolExecutor(max_workers=multiprocessing.cpu_count()) as executor:
        # Pass tolerance as a constant to all calls
        from functools import partial
        check_func = partial(_check_pair, tolerance=tolerance)
        
        for result in executor.map(check_func, tasks):
            if result:
                conflicts.append(result)

    if conflicts:
        error_msg = "Model Error: Volumetric intersections detected between parts!\n"
        for n1, n2, vol in conflicts:
            error_msg += f"  - '{n1}' and '{n2}' overlap by {vol:.6f} mm³\n"
        raise ValueError(error_msg)


def _aabb_intersects(bb1: cq.BoundBox, bb2: cq.BoundBox, buffer: float = 0.0) -> bool:
    """Check if two axis-aligned bounding boxes intersect."""
    if bb1.xmin > bb2.xmax + buffer or bb2.xmin > bb1.xmax + buffer:
        return False
    if bb1.ymin > bb2.ymax + buffer or bb2.ymin > bb1.ymax + buffer:
        return False
    if bb1.zmin > bb2.zmax + buffer or bb2.zmin > bb1.zmax + buffer:
        return False
    return True

