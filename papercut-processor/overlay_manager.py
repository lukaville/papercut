import ezdxf
from pathlib import Path
import sys

from typing import Any

def manage_overlays(project_dir: Path, overlay_config: dict[str, Any]) -> None:
    """Discover and validate overlay DXF files in the overlays/ directory."""
    overlays_dir = project_dir / "overlays"
    parts_dir = project_dir / "parts"

    if not overlays_dir.exists():
        return

    # Automatically discover all .dxf files in the overlays directory
    overlay_files = list(overlays_dir.glob("*.dxf"))
    if not overlay_files:
        return

    for overlay_path in overlay_files:
        part_name = overlay_path.stem
        part_dxf_path = parts_dir / f"{part_name}.dxf"
        
        # If exact match doesn't exist, look for disambiguated versions (e.g. part_name_grey.dxf)
        if not part_dxf_path.exists():
            matches = list(parts_dir.glob(f"{part_name}_*.dxf"))
            if matches:
                part_dxf_path = matches[0] # Use any one for geometry validation
        
        ref_path = part_dxf_path.with_suffix(".ref.dxf")
        match_path = ref_path if ref_path.exists() else part_dxf_path

        if not match_path.exists():
            print(f"Warning: Cannot validate overlay '{overlay_path.name}', part DXF not found at {parts_dir / f'{part_name}.dxf'}", file=sys.stderr)
            continue

        try:
            get_engraving_entities(overlay_path, match_path)
            print(f"  Overlay validated: {overlay_path.name}")
        except ValueError as e:
            raise ValueError(f"Overlay validation failed for '{part_name}': {e}")


def get_engraving_entities(overlay_path: Path, part_path: Path, flip_h: bool = False, flip_v: bool = False) -> tuple[list, any]:
    """Align overlay with part and return filtered engraving entities and transformation matrix."""
    from ezdxf import bbox
    from ezdxf.math import Matrix44, Vec3
    import math

    overlay_doc = ezdxf.readfile(overlay_path)
    part_doc = ezdxf.readfile(part_path)
    
    overlay_msp = overlay_doc.modelspace()
    part_msp = part_doc.modelspace()
    
    if flip_h or flip_v:
        pre_mat = Matrix44()
        if flip_h:
            pre_mat @= Matrix44.scale(-1, 1, 1)
        if flip_v:
            pre_mat @= Matrix44.scale(1, -1, 1)
        for e in overlay_msp:
            e.transform(pre_mat)
    
    # 1. Use robust ezdxf.bbox
    overlay_bb = bbox.extents(overlay_msp.query('LINE LWPOLYLINE CIRCLE ARC'))
    part_bb = bbox.extents(part_msp.query('LINE LWPOLYLINE CIRCLE ARC'))
    
    if not overlay_bb or not part_bb:
        raise ValueError("Could not determine bounding box of overlay or part")

    part_segments = []
    for e in part_msp:
        part_segments.extend(_get_entity_segments(e))

    # 2. Try 8 orientations (4 rotations * 2 flips) to find best orientation 
    # based on actual perimeter overlap.
    best_matched_length = -1
    best_mat = None
    
    for flip_x in [False, True]:
        for rotation_angle in [0, 90, 180, 270]:
            # Start with centering the overlay at its own origin
            mat = Matrix44.translate(-overlay_bb.extmin.x, -overlay_bb.extmin.y, -overlay_bb.extmin.z)
            
            if flip_x:
                mat @= Matrix44.scale(-1, 1, 1)
            
            mat @= Matrix44.z_rotate(math.radians(rotation_angle))
            
            # Find the new bounding box after flip and rotation to align back to (0,0)
            # We transform the corners of the original bounding box by the current partial matrix
            corners = [
                Vec3(overlay_bb.extmin.x, overlay_bb.extmin.y, overlay_bb.extmin.z),
                Vec3(overlay_bb.extmax.x, overlay_bb.extmin.y, overlay_bb.extmin.z),
                Vec3(overlay_bb.extmin.x, overlay_bb.extmax.y, overlay_bb.extmin.z),
                Vec3(overlay_bb.extmax.x, overlay_bb.extmax.y, overlay_bb.extmin.z),
            ]
            transformed_corners = [mat.transform(c) for c in corners]
            curr_min_x = min(c.x for c in transformed_corners)
            curr_min_y = min(c.y for c in transformed_corners)
            
            mat @= Matrix44.translate(-curr_min_x, -curr_min_y, 0)
            
            # Finally move to part's absolute minimum coordinates
            mat @= Matrix44.translate(part_bb.extmin.x, part_bb.extmin.y, part_bb.extmin.z)
            
            current_matched_length = 0
            for e in overlay_msp.query('LINE LWPOLYLINE'):
                for s_ov in _get_entity_segments(e):
                    ov_intervals = []
                    for s_part in part_segments:
                        # Use tighter tolerance for matching
                        iv = _get_segments_overlap_interval(s_ov, s_part, mat, tol=0.01)
                        if iv: ov_intervals.append(iv)
                    
                    if ov_intervals:
                        ov_intervals.sort()
                        c_s, c_e = ov_intervals[0]
                        for n_s, n_e in ov_intervals[1:]:
                            if n_s <= c_e: c_e = max(c_e, n_e)
                            else:
                                current_matched_length += (c_e - c_s)
                                c_s, c_e = n_s, n_e
                        current_matched_length += (c_e - c_s)
            
            if current_matched_length > best_matched_length:
                best_matched_length = current_matched_length
                best_mat = mat

    if best_matched_length < 10.0:
        raise ValueError(f"Outline mismatch. Only {best_matched_length:.1f}mm matched in any orientation.")

    mat = best_mat
    engravings = []
    matched_count = 0
    matched_length = 0

    # 3. Filter entities using the best matrix by geometrically subtracting overlaps
    for e in list(overlay_msp):
        segs = _get_entity_segments(e)
        if not segs:
            engravings.append(e)
            continue
            
        has_overlap = False
        for s_ov in segs:
            for s_part in part_segments:
                if _get_segments_overlap_interval(s_ov, s_part, mat, tol=0.01):
                    has_overlap = True
                    break
            if has_overlap: break
            
        if not has_overlap:
            engravings.append(e)
            continue
            
        for s_ov in segs:
            ov_len = _dist(s_ov[0], s_ov[1])
            ov_intervals = []
            for s_part in part_segments:
                iv = _get_segments_overlap_interval(s_ov, s_part, mat, tol=0.01)
                if iv: ov_intervals.append(iv)
            
            merged_intervals = []
            if ov_intervals:
                ov_intervals.sort()
                c_s, c_e = ov_intervals[0]
                for n_s, n_e in ov_intervals[1:]:
                    if n_s <= c_e: c_e = max(c_e, n_e)
                    else:
                        merged_intervals.append((c_s, c_e))
                        c_s, c_e = n_s, n_e
                merged_intervals.append((c_s, c_e))
            
            curr = 0.0
            remaining_intervals = []
            for s, e_inv in merged_intervals:
                if s > curr + 0.01:
                    remaining_intervals.append((curr, s))
                curr = max(curr, e_inv)
            if ov_len > curr + 0.01:
                remaining_intervals.append((curr, ov_len))
                
            for s, e_inv in remaining_intervals:
                dir_vec = (s_ov[1] - s_ov[0]).normalize()
                p_start = s_ov[0] + dir_vec * s
                p_end = s_ov[0] + dir_vec * e_inv
                new_line = overlay_msp.add_line(p_start, p_end)
                new_line.dxf.layer = e.dxf.layer
                if e.dxf.hasattr('color'):
                    new_line.dxf.color = e.dxf.color
                engravings.append(new_line)

    return engravings, mat


def _get_entity_segments(entity):
    """Break an entity into a list of (start, end) point tuples."""
    if entity.dxftype() == 'LINE':
        return [(entity.dxf.start, entity.dxf.end)]
    elif entity.dxftype() == 'LWPOLYLINE':
        pts = list(entity.get_points())
        segs = []
        for i in range(len(pts) - 1):
            segs.append((pts[i], pts[i+1]))
        if entity.closed:
            segs.append((pts[-1], pts[0]))
        return segs
    return []


def _dist(p1, p2):
    return ((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2)**0.5


def _get_segments_overlap_interval(s1, s2, mat, tol=0.01):
    """Return the interval (t_min, t_max) of overlap between s1 (transformed) and s2 if they are collinear."""
    from ezdxf.math import Vec3
    p1 = mat.transform(Vec3(s1[0]))
    p2 = mat.transform(Vec3(s1[1]))
    p3 = Vec3(s2[0])
    p4 = Vec3(s2[1])

    v1 = (p2 - p1)
    v2 = (p4 - p3)
    if v1.magnitude < tol or v2.magnitude < tol:
        return None
        
    # Absolute distance check for collinearity
    # Distance from line p1-p2 to point p3: |v1.cross(v13)| / |v1|
    v13 = (p3 - p1)
    dist = v1.cross(v13).magnitude / v1.magnitude
    if dist > tol:
        return None
        
    # Check if lines are parallel
    if v1.cross(v2).magnitude / (v1.magnitude * v2.magnitude) > 0.01: # 1% angle tol
        return None

    def project(p, origin, direction):
        return (p - origin).dot(direction.normalize())

    t1, t2 = 0, v1.magnitude
    t3 = project(p3, p1, v1)
    t4 = project(p4, p1, v1)
    
    t_min, t_max = min(t1, t2), max(t1, t2)
    u_min, u_max = min(t3, t4), max(t3, t4)
    
    overlap_min = max(t_min, u_min)
    overlap_max = min(t_max, u_max)
    
    if overlap_max > overlap_min + tol:
        return (overlap_min, overlap_max)
    return None
