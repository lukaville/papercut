"""Bridge (tab) generator for laser-cutting outlines.

Computes bridge positions on a closed polygon and applies them by splitting
the polygon into open segments with gaps (bridges) where the material is
left uncut.
"""

import math
from dataclasses import dataclass

from models import BridgeConfig


# Minimum offset from a polygon corner vertex when placing a bridge,
# expressed as a fraction of the edge length (clamped to at most half the edge).
_CORNER_OFFSET_FRACTION = 0.15
_CORNER_OFFSET_MIN_MM = 1.0


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
    """Compute a parametric offset to keep a bridge away from a polygon corner.

    Returns a t-offset (fraction of edge length) that ensures the bridge center
    is at least _CORNER_OFFSET_MIN_MM from the edge endpoint, while not exceeding
    half the edge.
    """
    if edge_length_mm < 1e-6:
        return 0.5

    offset_mm = max(_CORNER_OFFSET_MIN_MM, edge_length_mm * _CORNER_OFFSET_FRACTION)
    # Don't go past half the edge
    offset_mm = min(offset_mm, edge_length_mm * 0.5)
    # Also ensure the bridge itself fits
    half_bridge_t = (bridge_size_mm / 2.0) / edge_length_mm
    offset_t = offset_mm / edge_length_mm
    return max(offset_t, half_bridge_t + 0.01)


def _bridges_overlap(b1: Bridge, b2: Bridge, vertices: list[tuple[float, float]]) -> bool:
    """Check if two bridges on the same edge overlap or are too close."""
    if b1.edge_index != b2.edge_index:
        return False
    n = len(vertices)
    p0 = vertices[b1.edge_index]
    p1 = vertices[(b1.edge_index + 1) % n]
    length = _edge_length(p0, p1)
    if length < 1e-6:
        return True

    half1 = (b1.size_mm / 2.0) / length
    half2 = (b2.size_mm / 2.0) / length
    gap = abs(b1.t - b2.t) - half1 - half2
    return gap < 0.01  # Must have at least 1% of edge between bridges


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
        # --- Narrow/small part: 2 bridges on the two longest edges ---
        sorted_edges = sorted(range(n), key=lambda i: edge_lengths[i], reverse=True)

        placed_count = 0
        for edge_idx in sorted_edges:
            if placed_count >= 2:
                break
            length = edge_lengths[edge_idx]
            if length < bridge_size * 2:
                continue  # Edge too short for a bridge
            bridges.append(Bridge(edge_index=edge_idx, t=0.5, size_mm=bridge_size))
            placed_count += 1
    else:
        # --- Standard part: 4 bridges near bounding box corners ---
        corners = [
            (min_x, min_y),  # bottom-left
            (max_x, min_y),  # bottom-right
            (max_x, max_y),  # top-right
            (min_x, max_y),  # top-left
        ]

        for corner in corners:
            edge_idx, t_raw = _closest_edge_point_to_target(vertices, corner)
            length = edge_lengths[edge_idx]
            if length < bridge_size * 2:
                continue  # Edge too short

            # Offset the bridge away from the corner vertex
            offset_t = _offset_t_from_corner(length, bridge_size)
            # Determine which end of the edge is closer to the corner
            p0 = vertices[edge_idx]
            p1 = vertices[(edge_idx + 1) % n]
            d_start = math.hypot(p0[0] - corner[0], p0[1] - corner[1])
            d_end = math.hypot(p1[0] - corner[0], p1[1] - corner[1])

            if d_start <= d_end:
                t = offset_t
            else:
                t = 1.0 - offset_t
            t = max(0.0, min(1.0, t))

            candidate = Bridge(edge_index=edge_idx, t=t, size_mm=bridge_size)

            # Check for overlap with already placed bridges
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
        vertices: Ordered vertices of the polygon (no repeated closing vertex).
        bridges: Bridges to apply.
        closed: Whether the polyline is a closed polygon.

    Returns:
        List of open polyline segments (each a list of (x, y) tuples).
        The gaps between segments are the bridges.
    """
    if not bridges or len(vertices) < 2:
        if closed:
            return [vertices + [vertices[0]]]
        return [vertices]

    n = len(vertices)

    # Collect all cut points: for each bridge, compute start and end positions
    # as (edge_index, t) pairs, sorted by position along the polygon.
    cuts: list[tuple[int, float, int, float]] = []  # (edge, t_start, edge, t_end)

    for bridge in bridges:
        edge_idx = bridge.edge_index
        p0 = vertices[edge_idx]
        p1 = vertices[(edge_idx + 1) % n]
        length = _edge_length(p0, p1)

        if length < 1e-6:
            continue

        half_t = (bridge.size_mm / 2.0) / length
        t_start = bridge.t - half_t
        t_end = bridge.t + half_t

        # Clamp to [0, 1]
        t_start = max(0.0, t_start)
        t_end = min(1.0, t_end)

        if t_end <= t_start:
            continue

        cuts.append((edge_idx, t_start, edge_idx, t_end))

    if not cuts:
        if closed:
            return [vertices + [vertices[0]]]
        return [vertices]

    # Sort cuts by (edge_index, t_start)
    cuts.sort(key=lambda c: (c[0], c[1]))

    # Build segments by walking the polygon and skipping bridge gaps
    segments: list[list[tuple[float, float]]] = []
    current_segment: list[tuple[float, float]] = []

    # Determine the starting point: just after the last bridge gap
    # This ensures we produce contiguous segments even across the polygon wrap-around.
    # For simplicity, start at vertex 0 and handle wrap-around at the end.

    cut_idx = 0  # pointer into cuts list

    for edge_idx in range(n):
        p0 = vertices[edge_idx]
        p1 = vertices[(edge_idx + 1) % n]
        length = _edge_length(p0, p1)

        # Collect all cuts on this edge
        edge_cuts = []
        while cut_idx < len(cuts) and cuts[cut_idx][0] == edge_idx:
            edge_cuts.append((cuts[cut_idx][1], cuts[cut_idx][3]))
            cut_idx += 1

        if not edge_cuts:
            # No bridges on this edge — add start vertex
            current_segment.append(p0)
            if not closed and edge_idx == n - 1:
                current_segment.append(p1)
        else:
            # Walk along the edge, emitting points and breaking at gaps
            current_segment.append(p0)

            for t_start, t_end in edge_cuts:
                # Emit point at bridge start (end of current segment)
                if t_start > 0.0:
                    pt_start = _point_on_edge(p0, p1, t_start)
                    current_segment.append(pt_start)

                # Close current segment and start a new one after the gap
                if current_segment:
                    segments.append(current_segment)
                    current_segment = []

                if t_end < 1.0:
                    pt_end = _point_on_edge(p0, p1, t_end)
                    current_segment.append(pt_end)

            # If the edge ends after the last bridge, don't add p1 yet —
            # it will be added as p0 of the next edge iteration.
            # Exception: last edge of an open polyline.
            if not closed and edge_idx == n - 1:
                current_segment.append(p1)

    # Handle closure: connect last segment back to first if applicable
    if closed and segments and current_segment:
        # The current_segment runs from after the last bridge gap back to
        # vertex 0 (via the polygon wrap). Prepend first segment's points
        # to this segment to close the loop.
        current_segment.extend(segments[0])
        segments[0] = current_segment
    elif current_segment:
        segments.append(current_segment)

    # Filter out degenerate segments (single point or empty)
    segments = [seg for seg in segments if len(seg) >= 2]

    return segments


def _chain_lines_into_polygons(
    lines: list
) -> list[tuple[list[tuple[float, float]], list]]:
    """Chain LINE entities into closed polygons by matching endpoints.

    Args:
        lines: List of ezdxf LINE entities.

    Returns:
        List of (vertices, original_line_entities) tuples. Each vertices list
        is an ordered polygon (no repeated closing vertex). The line_entities
        list maps 1:1 to polygon edges for attribute preservation.
    """
    if not lines:
        return []

    # Build adjacency: map each rounded endpoint to the lines touching it
    ROUND = 4  # decimal places for coordinate rounding (~0.1µm tolerance)
    remaining = set(range(len(lines)))
    polygons: list[tuple[list[tuple[float, float]], list]] = []

    def _key(x: float, y: float) -> tuple[float, float]:
        return (round(x, ROUND), round(y, ROUND))

    def _start(line):
        return (line.dxf.start.x, line.dxf.start.y)

    def _end(line):
        return (line.dxf.end.x, line.dxf.end.y)

    while remaining:
        # Start a new chain from an arbitrary remaining line
        seed_idx = next(iter(remaining))
        remaining.remove(seed_idx)
        seed = lines[seed_idx]

        chain_vertices = [_start(seed), _end(seed)]
        chain_lines = [seed]

        # Extend the chain by finding lines whose start/end matches our chain's tail
        changed = True
        while changed:
            changed = False
            tail_key = _key(*chain_vertices[-1])

            for idx in list(remaining):
                line = lines[idx]
                sk = _key(*_start(line))
                ek = _key(*_end(line))

                if sk == tail_key:
                    chain_vertices.append(_end(line))
                    chain_lines.append(line)
                    remaining.remove(idx)
                    changed = True
                    break
                elif ek == tail_key:
                    chain_vertices.append(_start(line))
                    chain_lines.append(line)
                    remaining.remove(idx)
                    changed = True
                    break

        # Check if the chain closes (first vertex ≈ last vertex)
        if (len(chain_vertices) >= 4 and
            abs(chain_vertices[0][0] - chain_vertices[-1][0]) < 0.01 and
            abs(chain_vertices[0][1] - chain_vertices[-1][1]) < 0.01):
            # Remove the duplicate closing vertex
            chain_vertices = chain_vertices[:-1]

        if len(chain_vertices) >= 3:
            polygons.append((chain_vertices, chain_lines))

    return polygons


def add_bridges_to_cutting_block(
    block,
    bridge_config: BridgeConfig
) -> None:
    """Apply bridges to cutting geometry within an ezdxf block.

    Handles both LINE entities (produced by CadQuery's DXF exporter) and
    LWPOLYLINE entities. LINE entities are first chained into closed polygons,
    then bridges are applied by splitting edges with gaps.

    Modifies the block in place.

    Args:
        block: An ezdxf block definition containing cutting geometry.
        bridge_config: Bridge configuration.
    """
    if not bridge_config.enable:
        return

    # --- Handle LINE entities (CadQuery output) ---
    line_entities = [e for e in block if e.dxftype() == "LINE"]

    if line_entities:
        polygons = _chain_lines_into_polygons(line_entities)

        for vertices, original_lines in polygons:
            if len(vertices) < 3:
                continue

            # Compute bridge positions
            bridges = compute_bridge_positions(vertices, bridge_config)
            if not bridges:
                continue

            # Apply bridges to produce open segments
            segments = apply_bridges_to_polyline(vertices, bridges, closed=True)

            # Preserve DXF attributes from the first original line
            attribs = {}
            if original_lines:
                ref = original_lines[0]
                if hasattr(ref.dxf, 'layer'):
                    attribs['layer'] = ref.dxf.layer

            # Delete original LINE entities that formed this polygon
            for line in original_lines:
                try:
                    block.delete_entity(line)
                except Exception:
                    pass

            # Add new open polyline segments as LWPOLYLINE (more compact than individual LINEs)
            for seg in segments:
                block.add_lwpolyline(seg, close=False, dxfattribs=attribs)

    # --- Handle LWPOLYLINE entities ---
    polylines = [e for e in block if e.dxftype() == "LWPOLYLINE"]

    for polyline in polylines:
        # Extract vertices and closed flag
        with polyline.points("xy") as points:
            vertices = list(points)

        if len(vertices) < 3:
            continue

        is_closed = polyline.is_closed

        # Remove duplicate closing vertex if present
        if (len(vertices) > 1 and
            abs(vertices[0][0] - vertices[-1][0]) < 1e-6 and
            abs(vertices[0][1] - vertices[-1][1]) < 1e-6):
            vertices = vertices[:-1]
            is_closed = True

        if len(vertices) < 3:
            continue

        # Compute bridge positions
        bridges = compute_bridge_positions(vertices, bridge_config)
        if not bridges:
            continue

        # Apply bridges to produce open segments
        segments = apply_bridges_to_polyline(vertices, bridges, closed=is_closed)

        # Get the original entity's DXF attributes
        attribs = {}
        if hasattr(polyline.dxf, 'layer'):
            attribs['layer'] = polyline.dxf.layer
        if hasattr(polyline.dxf, 'color') and polyline.dxf.color is not None:
            attribs['color'] = polyline.dxf.color

        # Delete the original polyline
        block.delete_entity(polyline)

        # Add new open polyline segments
        for seg in segments:
            block.add_lwpolyline(seg, close=False, dxfattribs=attribs)

