"""Bridge (tab) generator for laser-cutting outlines.

Computes bridge positions on a closed polygon and applies them by splitting
the polygon into open segments with gaps (bridges) where the material is
left uncut.
"""

import math
from dataclasses import dataclass
from typing import Optional

from models import BridgeConfig


# Minimum offset from a polygon corner vertex when placing a bridge,
# expressed as a fraction of the edge length (clamped to at most half the edge).
# Now superseded by direct adjancency logic.


@dataclass
class Bridge:
    """A bridge (tab) on a polygon edge.

    Attributes:
        edge_index: Index of the edge in the polygon vertex list.
        t: Parametric position along the edge [0.0, 1.0], where 0.0 is the
           start vertex and 1.0 is the end vertex. The bridge is centered here.
        size_mm: Length of the bridge gap in mm.
    """
    edge_index: int
    t: float
    size_mm: float


def _edge_length(p0: tuple[float, float], p1: tuple[float, float]) -> float:
    """Euclidean distance between two 2D points."""
    return math.hypot(p1[0] - p0[0], p1[1] - p0[1])


def _point_on_edge(p0: tuple[float, float], p1: tuple[float, float], t: float) -> tuple[float, float]:
    """Interpolate along an edge at parametric position t ∈ [0, 1]."""
    return (p0[0] + t * (p1[0] - p0[0]),
            p0[1] + t * (p1[1] - p0[1]))


def _closest_edge_point_to_target(
    vertices: list[tuple[float, float]],
    target: tuple[float, float]
) -> tuple[int, float]:
    """Find the edge and parametric position closest to a target point.

    Returns:
        (edge_index, t) where t ∈ [0, 1].
    """
    best_dist = float('inf')
    best_edge = 0
    best_t = 0.0
    n = len(vertices)

    for i in range(n):
        p0 = vertices[i]
        p1 = vertices[(i + 1) % n]
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        length_sq = dx * dx + dy * dy

        if length_sq < 1e-12:
            # Degenerate edge
            t = 0.0
        else:
            t = ((target[0] - p0[0]) * dx + (target[1] - p0[1]) * dy) / length_sq
            t = max(0.0, min(1.0, t))

        pt = _point_on_edge(p0, p1, t)
        dist = math.hypot(pt[0] - target[0], pt[1] - target[1])

        if dist < best_dist:
            best_dist = dist
            best_edge = i
            best_t = t

    return best_edge, best_t


def _offset_t_from_corner(edge_length_mm: float, bridge_size_mm: float) -> float:
    """Compute the normalized t-offset for a bridge to be adjacent to a corner."""
    if edge_length_mm < 1e-6:
        return 0.0
    # Place bridge immediately adjacent to the corner vertex.
    # The gap should start at t=0 or t=1, so its center is at half the bridge size.
    offset_mm = bridge_size_mm / 2.0
    # Ensure we don't go past the midpoint of the edge
    offset_mm = min(offset_mm, edge_length_mm * 0.5)
    return offset_mm / edge_length_mm


def _bridges_overlap(b1: Bridge, b2: Bridge, vertices: list[tuple[float, float]]) -> bool:
    """Check if two bridges are too close to each other, even on different edges."""
    def get_pos(b: Bridge):
        p0 = vertices[b.edge_index]
        p1 = vertices[(b.edge_index + 1) % len(vertices)]
        return (p0[0] + b.t * (p1[0] - p0[0]), p0[1] + b.t * (p1[1] - p0[1]))

    pos1 = get_pos(b1)
    pos2 = get_pos(b2)
    dist = math.hypot(pos1[0] - pos2[0], pos1[1] - pos2[1])
    
    # Bridges should be separated by at least their combined size plus a buffer
    # to avoid double-weakening a corner.
    min_dist = (b1.size_mm + b2.size_mm) * 1.5
    return dist < min_dist


def compute_bridge_positions(
    vertices: list[tuple[float, float]],
    config: BridgeConfig
) -> list[Bridge]:
    """Compute bridge positions for a closed polygon.

    Args:
        vertices: Ordered vertices of a closed polygon (no repeated closing vertex).
        config: Bridge configuration.

    Returns:
        List of Bridge instances describing where to place gaps.
    """
    if len(vertices) < 3:
        return []

    n = len(vertices)
    bridge_size = config.size_mm

    # Compute bounding box
    xs = [v[0] for v in vertices]
    ys = [v[1] for v in vertices]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    width = max_x - min_x
    height = max_y - min_y

    # Compute edge lengths
    edge_lengths: list[float] = []
    for i in range(n):
        p0 = vertices[i]
        p1 = vertices[(i + 1) % n]
        edge_lengths.append(_edge_length(p0, p1))

    min_dim = min(width, height)
    is_narrow = min_dim < config.min_size_all_corners_mm

    bridges: list[Bridge] = []

    if is_narrow:
        # --- Narrow/small part: 2 bridges at the two most distant corners of the bounding box ---
        # This handles cases where long edges are split into many small segments.
        min_x = min(v[0] for v in vertices)
        max_x = max(v[0] for v in vertices)
        min_y = min(v[1] for v in vertices)
        max_y = max(v[1] for v in vertices)

        # We'll try the two primary diagonals: BL-TR and BR-TL
        # and pick the one that aligns with the "longest" dimension.
        if (max_x - min_x) >= (max_y - min_y):
            # Horizontal-ish part: use opposite horizontal ends
            diag_corners = [(min_x, min_y), (max_x, max_y)]
        else:
            # Vertical-ish part: use opposite vertical ends
            diag_corners = [(min_x, min_y), (max_x, max_y)] # BL to TR
            # Actually, just two furthest corners is enough
            
        for corner in diag_corners:
            edge_idx, t_raw = _closest_edge_point_to_target(vertices, corner)
            length = edge_lengths[edge_idx]
            if length < bridge_size: # Even smaller tolerance for narrow parts
                continue

            # Offset logic consistent with standard parts
            if t_raw < 0.5:
                t = _offset_t_from_corner(length, bridge_size)
            else:
                t = 1.0 - _offset_t_from_corner(length, bridge_size)
            
            candidate = Bridge(edge_index=edge_idx, t=t, size_mm=bridge_size)
            if not any(_bridges_overlap(candidate, b, vertices) for b in bridges):
                bridges.append(candidate)
    else:
        # --- Standard part: 4 bridges near bounding box corners ---
        # Find the vertices closest to the four corners of the bounding box
        min_x = min(v[0] for v in vertices)
        max_x = max(v[0] for v in vertices)
        min_y = min(v[1] for v in vertices)
        max_y = max(v[1] for v in vertices)

        corners = [
            (min_x, min_y), (max_x, min_y),
            (max_x, max_y), (min_x, max_y)
        ]
        
        # --- Add extra intermediate bridges if the part is very large ---
        # We use the bounding box to determine intermediate positions
        # because long edges might be split into many small segments.
        min_length = config.min_length_extra_bridge_mm
        
        # Bottom edge intermediate points
        if max_x - min_x > min_length:
            num = max(2, math.ceil((max_x - min_x) / min_length))
            for i in range(1, num):
                corners.append((min_x + i * (max_x - min_x) / num, min_y))
        
        # Top edge intermediate points
        if max_x - min_x > min_length:
            num = max(2, math.ceil((max_x - min_x) / min_length))
            for i in range(1, num):
                corners.append((min_x + i * (max_x - min_x) / num, max_y))
                
        # Left edge intermediate points
        if max_y - min_y > min_length:
            num = max(2, math.ceil((max_y - min_y) / min_length))
            for i in range(1, num):
                corners.append((min_x, min_y + i * (max_y - min_y) / num))
                
        # Right edge intermediate points
        if max_y - min_y > min_length:
            num = max(2, math.ceil((max_y - min_y) / min_length))
            for i in range(1, num):
                corners.append((max_x, min_y + i * (max_y - min_y) / num))

        for corner in corners:
            edge_idx, t_raw = _closest_edge_point_to_target(vertices, corner)
            length = edge_lengths[edge_idx]
            if length < bridge_size * 2:
                continue

            # Offset the bridge away from the corner vertex if we are near one,
            # otherwise just use the target t.
            # But wait, to keep it simple and consistent with user request:
            # If we are near a vertex, use the zero-gap offset.
            # If we are in the middle of an edge, just use t_raw.
            
            if t_raw < 0.1: # Near start vertex
                t = _offset_t_from_corner(length, bridge_size)
            elif t_raw > 0.9: # Near end vertex
                t = 1.0 - _offset_t_from_corner(length, bridge_size)
            else:
                t = t_raw
            
            candidate = Bridge(edge_index=edge_idx, t=t, size_mm=bridge_size)
            if not any(_bridges_overlap(candidate, b, vertices) for b in bridges):
                bridges.append(candidate)

    # --- Extra midpoint bridges for long edges ---
    _add_extra_bridges_on_long_edges(vertices, edge_lengths, bridges, config)

    return bridges


def _add_extra_bridges_on_long_edges(
    vertices: list[tuple[float, float]],
    edge_lengths: list[float],
    bridges: list[Bridge],
    config: BridgeConfig
) -> None:
    """Add extra bridges along edges that exceed min_length_extra_bridge_mm.

    Distributes bridges evenly along the edge, avoiding overlap with existing
    bridges. Modifies `bridges` in place.
    """
    n = len(vertices)
    min_length = config.min_length_extra_bridge_mm
    bridge_size = config.size_mm

    for edge_idx in range(n):
        length = edge_lengths[edge_idx]
        if length < min_length:
            continue

        # How many segments should this edge be divided into?
        # We want spacing ≤ min_length_extra_bridge_mm between bridges.
        num_segments = max(2, math.ceil(length / min_length))
        # Place bridges at segment boundaries (not at 0.0 or 1.0 which are vertices)
        for seg in range(1, num_segments):
            t = seg / num_segments
            candidate = Bridge(edge_index=edge_idx, t=t, size_mm=bridge_size)
            if not any(_bridges_overlap(candidate, b, vertices) for b in bridges):
                bridges.append(candidate)


def apply_bridges_to_polyline(
    vertices: list[tuple[float, float]],
    bridges: list[Bridge],
    closed: bool = True
) -> list[list[tuple[float, float]]]:
    """Split a polyline at bridge locations, producing open segments with gaps.

    Args:
        vertices: Ordered vertices of the polygon. If closed, V[n-1] connects to V[0].
        bridges: Bridges to apply.
        closed: Whether the polyline is a closed polygon.

    Returns:
        List of open polyline segments (each a list of (x, y) tuples).
    """
    if not bridges or len(vertices) < 2:
        if closed:
            return [vertices + [vertices[0]]]
        return [vertices]

    n = len(vertices)
    num_edges = n if closed else n - 1

    # 1. Collect all bridge intervals as (edge_index, t_start, t_end)
    # t is normalized [0, 1] along each edge.
    intervals = []
    for bridge in bridges:
        edge_idx = bridge.edge_index
        p0 = vertices[edge_idx]
        p1 = vertices[(edge_idx + 1) % n]
        length = _edge_length(p0, p1)
        if length < 1e-6:
            continue
        half_t = (bridge.size_mm / 2.0) / length
        t_start = max(0.0, bridge.t - half_t)
        t_end = min(1.0, bridge.t + half_t)
        if t_end > t_start:
            intervals.append((edge_idx, t_start, t_end))

    # Sort intervals by edge_index then t_start
    intervals.sort()

    # 2. Build the result by walking the polyline and cutting out intervals
    segments = []
    current_segment = []

    # Helper to add a point if it's not a duplicate of the last point
    def add_pt(p):
        if not current_segment:
            current_segment.append(p)
            return
        last = current_segment[-1]
        if abs(p[0] - last[0]) > 1e-9 or abs(p[1] - last[1]) > 1e-9:
            current_segment.append(p)

    def close_segment():
        nonlocal current_segment
        if current_segment:
            segments.append(current_segment)
        current_segment = []

    # Current position in the walk
    curr_edge = 0
    curr_t = 0.0

    for edge_idx, t0, t1 in intervals:
        # Walk from curr position to t0
        while curr_edge < edge_idx:
            # Finish current edge
            p0 = vertices[curr_edge]
            p1 = vertices[(curr_edge + 1) % n]
            add_pt(_point_on_edge(p0, p1, curr_t))
            add_pt(p1)
            curr_edge += 1
            curr_t = 0.0
        
        # Now we are at edge_idx, curr_t. Walk to t0.
        p0 = vertices[edge_idx]
        p1 = vertices[(edge_idx + 1) % n]
        add_pt(_point_on_edge(p0, p1, curr_t))
        add_pt(_point_on_edge(p0, p1, t0))
        
        # Close segment (bridge gap starts)
        close_segment()
        
        # Set next start position to t1
        curr_t = t1

    # 3. Walk to the end of the polyline
    while curr_edge < num_edges:
        p0 = vertices[curr_edge]
        p1 = vertices[(curr_edge + 1) % n]
        add_pt(_point_on_edge(p0, p1, curr_t))
        add_pt(p1)
        curr_edge += 1
        curr_t = 0.0

    # 4. Handle closure: merge the last and first segments if applicable
    if closed and segments and current_segment:
        # Check if they are actually continuous (should be vertex 0)
        p_last = current_segment[-1]
        p_first = segments[0][0]
        if abs(p_last[0] - p_first[0]) < 1e-6 and abs(p_last[1] - p_first[1]) < 1e-6:
            current_segment.extend(segments[0][1:])
            segments[0] = current_segment
        else:
            # They are separated by a bridge at the junction
            close_segment()
    elif current_segment:
        close_segment()

    # Final filter: remove degenerate segments
    return [seg for seg in segments if len(seg) >= 2]


def _chain_lines_into_polygons(
    lines: list
) -> list[tuple[list[tuple[float, float]], list, bool]]:
    """Chain LINE entities into closed or open polygons by matching endpoints.

    Args:
        lines: List of ezdxf LINE entities.

    Returns:
        List of (vertices, original_line_entities, is_closed) tuples.
    """
    if not lines:
        return []

    ROUND = 4
    remaining = set(range(len(lines)))
    polygons: list[tuple[list[tuple[float, float]], list, bool]] = []

    def _key(x: float, y: float) -> tuple[float, float]:
        return (round(x, ROUND), round(y, ROUND))

    while remaining:
        seed_idx = next(iter(remaining))
        remaining.remove(seed_idx)
        seed = lines[seed_idx]

        chain_vertices = [(seed.dxf.start.x, seed.dxf.start.y),
                          (seed.dxf.end.x, seed.dxf.end.y)]
        chain_lines = [seed]

        changed = True
        while changed:
            changed = False
            tail_key = _key(*chain_vertices[-1])

            for idx in list(remaining):
                line = lines[idx]
                sk = _key(line.dxf.start.x, line.dxf.start.y)
                ek = _key(line.dxf.end.x, line.dxf.end.y)

                if sk == tail_key:
                    chain_vertices.append((line.dxf.end.x, line.dxf.end.y))
                    chain_lines.append(line)
                    remaining.remove(idx)
                    changed = True
                    break
                elif ek == tail_key:
                    chain_vertices.append((line.dxf.start.x, line.dxf.start.y))
                    chain_lines.append(line)
                    remaining.remove(idx)
                    changed = True
                    break

        # Check if the chain closes (tolerance: 0.1mm)
        is_closed = False
        if (len(chain_vertices) >= 4 and
            abs(chain_vertices[0][0] - chain_vertices[-1][0]) < 0.1 and
            abs(chain_vertices[0][1] - chain_vertices[-1][1]) < 0.1):
            chain_vertices = chain_vertices[:-1]
            is_closed = True

        if len(chain_vertices) >= 2:
            polygons.append((chain_vertices, chain_lines, is_closed))

    return polygons


def _polygon_area(vertices: list[tuple[float, float]]) -> float:
    """Compute the absolute area of a polygon using the shoelace formula."""
    n = len(vertices)
    if n < 3:
        return 0.0
    area = 0.0
    for i in range(n):
        x0, y0 = vertices[i]
        x1, y1 = vertices[(i + 1) % n]
        area += x0 * y1 - x1 * y0
    return abs(area) / 2.0


def _find_outer_contour_index(
    polygons: list[tuple[list[tuple[float, float]], list, bool]]
) -> Optional[int]:
    """Find the index of the outer contour among a list of polygons."""
    if not polygons:
        return None
    best_idx = 0
    best_area = -1.0
    for i, (verts, _, _) in enumerate(polygons):
        area = _polygon_area(verts)
        if area > best_area:
            best_area = area
            best_idx = i
    return best_idx


def compute_overcuts(
    vertices: list[tuple[float, float]],
    bridges: list[Bridge],
    config: BridgeConfig
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Generate overcut lines for bridges located at convex corner vertices.

    Args:
        vertices: List of polygon vertices.
        bridges: List of Bridge objects.
        config: Bridge configuration.

    Returns:
        List of (start_pt, end_pt) tuples representing overcut lines.
    """
    if not config.overcut:
        return []

    n = len(vertices)
    if n < 3:
        return []

    # Calculate winding order (Area > 0 means CCW)
    area = 0.0
    for i in range(n):
        p0, p1 = vertices[i], vertices[(i + 1) % n]
        area += p0[0] * p1[1] - p1[0] * p0[1]
    is_ccw = area > 0

    overcut_lines = []
    L_over = config.overcut_length_mm

    for b in bridges:
        # Bridge is on edge b.edge_index: vertices[i] -> vertices[i+1]
        i = b.edge_index
        p_prev = vertices[(i - 1 + n) % n]
        p0 = vertices[i]
        p1 = vertices[(i + 1) % n]
        p2 = vertices[(i + 2) % n]
        
        L = _edge_length(p0, p1)
        if L < 1e-6:
            continue
        half_t = (b.size_mm / 2.0) / L
        
        # 1. Check if bridge gap touches start vertex p0
        if b.t - half_t < 1e-6:
            # Vertex p0 is the junction between (p_prev -> p0) and (p0 -> p1)
            # Check if this corner is convex
            v1 = (p0[0] - p_prev[0], p0[1] - p_prev[1])
            v2 = (p1[0] - p0[0], p1[1] - p0[1])
            cross = v1[0] * v2[1] - v1[1] * v2[0]
            
            # In CCW, cross > 0 is convex (left turn). In CW, cross < 0 is convex.
            is_convex = (cross > 1e-6) if is_ccw else (cross < -1e-6)
            
            if is_convex:
                ux, uy = (p1[0] - p0[0]) / L, (p1[1] - p0[1]) / L
                overcut_lines.append((p0, (p0[0] - ux * L_over, p0[1] - uy * L_over)))
            
        # 2. Check if bridge gap touches end vertex p1
        if b.t + half_t > 1.0 - 1e-6:
            # Vertex p1 is the junction between (p0 -> p1) and (p1 -> p2)
            v1 = (p1[0] - p0[0], p1[1] - p0[1])
            v2 = (p2[0] - p1[0], p2[1] - p1[1])
            cross = v1[0] * v2[1] - v1[1] * v2[0]
            
            is_convex = (cross > 1e-6) if is_ccw else (cross < -1e-6)
            
            if is_convex:
                ux, uy = (p1[0] - p0[0]) / L, (p1[1] - p0[1]) / L
                overcut_lines.append((p1, (p1[0] + ux * L_over, p1[1] + uy * L_over)))

    return overcut_lines


def add_bridges_to_cutting_block(
    block,
    bridge_config: BridgeConfig
) -> None:
    """Apply bridges to cutting geometry within an ezdxf block.

    Handles both LINE entities (produced by CadQuery's DXF exporter) and
    LWPOLYLINE entities. Collects all shapes, identifies the outer contour
    (largest area), and applies bridges only to it. All original cutting
    geometry is replaced.

    Modifies the block in place.

    Args:
        block: An ezdxf block definition containing cutting geometry.
        bridge_config: Bridge configuration.
    """
    if not bridge_config.enable:
        return

    all_polygons: list[tuple[list[tuple[float, float]], list, bool]] = []

    # 1. Collect LINE entities and chain them
    line_entities = [e for e in block if e.dxftype() == "LINE"]
    if line_entities:
        chained = _chain_lines_into_polygons(line_entities)
        all_polygons.extend(chained)

    # 2. Collect LWPOLYLINE entities
    polyline_entities = [e for e in block if e.dxftype() == "LWPOLYLINE"]
    for polyline in polyline_entities:
        with polyline.points("xy") as points:
            vertices = list(points)
        if len(vertices) < 2:
            continue
        is_closed = polyline.is_closed
        # Remove duplicate closing vertex if present
        if (len(vertices) > 1 and
            abs(vertices[0][0] - vertices[-1][0]) < 1e-6 and
            abs(vertices[0][1] - vertices[-1][1]) < 1e-6):
            vertices = vertices[:-1]
            is_closed = True
        all_polygons.append((vertices, [polyline], is_closed))

    if not all_polygons:
        return

    # 3. Find the outer contour (largest area)
    best_idx = _find_outer_contour_index(all_polygons)
    if best_idx is None:
        return

    # 4. Process all polygons
    for i, (vertices, original_entities, is_closed) in enumerate(all_polygons):
        if i == best_idx and len(vertices) >= 2:
            # This is the outer contour — apply bridges
            bridges = compute_bridge_positions(vertices, bridge_config)
            if bridges:
                segments = apply_bridges_to_polyline(vertices, bridges, closed=is_closed)
                overcuts = compute_overcuts(vertices, bridges, bridge_config)
                
                attribs = {}
                ref = original_entities[0]
                if hasattr(ref.dxf, 'layer'):
                    attribs['layer'] = ref.dxf.layer
                if hasattr(ref.dxf, 'color') and ref.dxf.color is not None:
                    attribs['color'] = ref.dxf.color

                for ent in original_entities:
                    try:
                        block.delete_entity(ent)
                    except Exception:
                        pass
                
                # Add bridged segments
                for seg in segments:
                    block.add_lwpolyline(seg, close=False, dxfattribs=attribs)
                
                # Add overcut lines
                for start, end in overcuts:
                    block.add_line(start, end, dxfattribs=attribs)
                
                continue

        # For non-outer polygons (holes), convert LINEs to LWPOLYLINE for consistency
        ref = original_entities[0]
        if ref.dxftype() == "LINE":
            attribs = {'layer': ref.dxf.layer} if hasattr(ref.dxf, 'layer') else {}
            for ent in original_entities:
                try:
                    block.delete_entity(ent)
                except Exception:
                    pass
            # Add as a single (possibly closed) polyline
            pts = vertices + ([vertices[0]] if is_closed else [])
            block.add_lwpolyline(pts, close=False, dxfattribs=attribs)



