import ezdxf
from ezdxf.addons.importer import Importer
from pathlib import Path
import sys
import uuid
from models import Part, SheetConfig, PlacementConfig, SheetResult, PlacedPart
from dxf_exporter import get_dxf_layer_svg_paths

def index_to_letters(n: int) -> str:
    """Convert a 0-indexed integer to spreadsheet letters (A, B, C, ..., AA, AB)."""
    letters = ""
    n += 1
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters

class MaxRectsBinPacker:
    """Implementation of the MaxRects 2D Bin Packing algorithm (Bottom-Left Choice)."""
    
    def __init__(self, width: float, height: float, p_margin: float = 0.0):
        self.width = width
        self.height = height
        self.p_margin = p_margin
        # Start with one maximal free rectangle covering the whole sheet
        self.free_rects = [(0.0, 0.0, width, height)]
        self.used_rects = []

    def insert(self, w: float, h: float) -> tuple[float, float, bool] | None:
        """Try to insert a part of size (w, h) using the Best Short Side Fit (BSSF) heuristic.
        Returns (x, y, rotated) or None if it doesn't fit.
        """
        best_short_side_fit = float('inf')
        best_long_side_fit = float('inf')
        best_rotated = False
        best_rect = None

        # Try both orientations
        for rotated in [False, True]:
            # The dimension we pack includes the part margin on one side
            # (the other side's margin is provided by the next part's bx/by).
            # Wait, actually, to be consistent, we should use (w + margin) x (h + margin).
            rw, rh = (h + self.p_margin, w + self.p_margin) if rotated else (w + self.p_margin, h + self.p_margin)
            
            for fx, fy, fw, fh in self.free_rects:
                if fw >= rw and fh >= rh:
                    # BSSF Rule: minimize leftover space in the shorter dimension
                    leftover_w = fw - rw
                    leftover_h = fh - rh
                    short_side_fit = min(leftover_w, leftover_h)
                    long_side_fit = max(leftover_w, leftover_h)
                    
                    if short_side_fit < best_short_side_fit or (short_side_fit == best_short_side_fit and long_side_fit < best_long_side_fit):
                        best_short_side_fit = short_side_fit
                        best_long_side_fit = long_side_fit
                        best_rotated = rotated
                        # We store the uninflated size for 'bx, by' logic, but we must use inflated for splitting
                        best_rect = (fx, fy, rw, rh)

        if best_rect is None:
            # Special case: if the part is at the very edge of the bin, 
            # we might not need the margin on the right/top.
            # But for simplicity and robustness, we enforce it everywhere.
            # However, a part that ALMOST fits (e.g. 190mm in a 190mm bin)
            # would fail if we add margin.
            # Let's try fitting WITHOUT the extra margin if it's the very last part of the bin.
            for rotated in [False, True]:
                rw_raw, rh_raw = (h, w) if rotated else (w, h)
                for fx, fy, fw, fh in self.free_rects:
                    if fw >= rw_raw and fh >= rh_raw:
                        # Check if it fits if we clip the margin to the bin boundary
                        needed_w = min(rw_raw + self.p_margin, self.width - fx)
                        needed_h = min(rh_raw + self.p_margin, self.height - fy)
                        if fw >= needed_w and fh >= needed_h:
                            leftover_w = fw - needed_w
                            leftover_h = fh - needed_h
                            short_side_fit = min(leftover_w, leftover_h)
                            if short_side_fit < best_short_side_fit:
                                best_short_side_fit = short_side_fit
                                best_rotated = rotated
                                best_rect = (fx, fy, needed_w, needed_h)

        if best_rect is None:
            return None

        bx, by, bw, bh = best_rect
        used_for_split = (bx, by, bw, bh)
        
        self.used_rects.append(best_rect)
        
        # Update free rectangles
        new_free_rects = []
        for fr in self.free_rects:
            split_rects = self._split(fr, used_for_split)
            new_free_rects.extend(split_rects)
        
        self.free_rects = self._prune(new_free_rects)
        return bx, by, best_rotated

    def _split(self, free: tuple[float, float, float, float], used: tuple[float, float, float, float]) -> list[tuple[float, float, float, float]]:
        """Split a free rectangle by a used rectangle into up to 4 smaller free rectangles."""
        fx, fy, fw, fh = free
        ux, uy, uw, uh = used

        # Check for overlap
        if ux >= fx + fw or ux + uw <= fx or uy >= fy + fh or uy + uh <= fy:
            return [free]

        result = []
        # Left split
        if ux > fx:
            result.append((fx, fy, ux - fx, fh))
        # Right split
        if ux + uw < fx + fw:
            result.append((ux + uw, fy, fx + fw - (ux + uw), fh))
        # Bottom split
        if uy > fy:
            result.append((fx, fy, fw, uy - fy))
        # Top split
        if uy + uh < fy + fh:
            result.append((fx, uy + uh, fw, fy + fh - (uy + uh)))

        return result


    def _prune(self, rects: list[tuple[float, float, float, float]]) -> list[tuple[float, float, float, float]]:
        """Remove rectangles that are fully contained within others."""
        unique_rects = []
        for i, r1 in enumerate(rects):
            is_contained = False
            for j, r2 in enumerate(rects):
                if i == j: continue
                # Check if r1 is contained in r2
                if (r1[0] >= r2[0] and r1[1] >= r2[1] and 
                    r1[0] + r1[2] <= r2[0] + r2[2] and 
                    r1[1] + r1[3] <= r2[1] + r2[3]):
                    is_contained = True
                    break
            if not is_contained:
                unique_rects.append(r1)
        return unique_rects


def place_parts(
    parts: list[Part],
    sheets_config: list[SheetConfig],
    placement_config: PlacementConfig
) -> list[SheetResult]:
    """Place parts on sheets using the MaxRects algorithm with multi-sheet backfilling."""
    if not parts:
        return []

    # Normalize sheet colors for comparison
    def normalize_hex(h: str) -> str:
        h = h.lower().lstrip('#')
        if len(h) == 3:
            h = ''.join(c*2 for c in h)
        return '#' + h

    sheet_by_color = {normalize_hex(s.color): s for s in sheets_config}

    # Group parts by color
    parts_by_color = {}
    for p in parts:
        color = normalize_hex(p.color.hex if p.color else "#000000")
        parts_by_color.setdefault(color, []).append(p)

    # Check for missing colors
    missing_colors = [c for c in parts_by_color if c not in sheet_by_color]
    if missing_colors:
        error_msg = "Configuration Error: No sheets found for the following part colors:\n"
        for color in missing_colors:
            parts_str = ", ".join(sorted(list(set(p.name for p in parts_by_color[color]))))
            error_msg += f"  - {color} (Parts: {parts_str})\n"
        raise ValueError(error_msg)

    results = []
    # Track packers per color to allow multi-sheet backfilling
    color_packers = {} # color -> list[(packer, SheetResult)]

    sorted_colors = sorted(parts_by_color.keys())
    for color in sorted_colors:
        color_parts = parts_by_color[color]
        sheet_config = sheet_by_color[color]
        
        # Flatten parts into a single list of individual items
        to_place = []
        for p in color_parts:
            for _ in range(p.count):
                to_place.append(p)
        
        # Sort by max(width, height) descending - a strong heuristic for MaxRects
        to_place.sort(key=lambda p: max(p.width_mm, p.height_mm), reverse=True)

        for p in to_place:
            margin = placement_config.sheet_margin_mm
            p_margin = placement_config.part_margin_mm
            
            # Try to fit in existing sheets for this color
            placed = False
            for packer, res in color_packers.get(color, []):
                fit = packer.insert(p.width_mm, p.height_mm)
                if fit:
                    bx, by, rotated = fit
                    # Validation: Ensure part is within sheet bounds
                    final_x = bx + margin
                    final_y = by + margin
                    rw, rh = (p.height_mm, p.width_mm) if rotated else (p.width_mm, p.height_mm)
                    if (final_x + rw > sheet_config.width_mm + 0.01 or 
                        final_y + rh > sheet_config.height_mm + 0.01 or
                        final_x < -0.01 or final_y < -0.01):
                        raise ValueError(f"Placement BUG: Part '{p.name}' placed outside sheet '{sheet_config.name}' at ({final_x:.1f}, {final_y:.1f}) with size {rw:.1f}x{rh:.1f}.")

                    res.placed_parts.append(PlacedPart(p.name, final_x, final_y, p.width_mm, p.height_mm, rotated))
                    res.total_parts_area_mm2 += p.area_mm2
                    placed = True
                    break
            
            if not placed:
                # Create a new sheet
                available_w = sheet_config.width_mm - 2 * margin
                available_h = sheet_config.height_mm - 2 * margin
                
                packer = MaxRectsBinPacker(available_w, available_h, p_margin)
                
                # Reserve space for the label square in the Top-Left corner
                l_size = placement_config.label_square_size_mm
                # We add p_margin to the reservation so that parts keep their distance
                # just like they do from each other.
                # Label at (0, available_h - l_size) in packer space.
                # We inflate it by p_margin on the 'inside' edges.
                label_rect_with_margin = (0.0, available_h - l_size - p_margin, l_size + p_margin, l_size + p_margin)
                
                new_free_rects = []
                for fr in packer.free_rects:
                    split = packer._split(fr, label_rect_with_margin)
                    new_free_rects.extend(split)
                packer.free_rects = packer._prune(new_free_rects)
                packer.used_rects.append(label_rect_with_margin)
                
                # Now insert the actual part
                fit = packer.insert(p.width_mm, p.height_mm)
                if not fit:
                    raise ValueError(f"Part '{p.name}' ({p.width_mm:.1f}x{p.height_mm:.1f}mm) is too large for sheet '{sheet_config.name}'.")
                
                bx, by, rotated = fit
                
                # Validation: Ensure part is within sheet bounds
                final_x = bx + margin
                final_y = by + margin
                rw, rh = (p.height_mm, p.width_mm) if rotated else (p.width_mm, p.height_mm)
                if (final_x + rw > sheet_config.width_mm + 0.01 or 
                    final_y + rh > sheet_config.height_mm + 0.01 or
                    final_x < -0.01 or final_y < -0.01):
                    raise ValueError(f"Placement BUG: Part '{p.name}' placed outside sheet '{sheet_config.name}' at ({final_x:.1f}, {final_y:.1f}) with size {rw:.1f}x{rh:.1f}.")

                sheet_label = index_to_letters(len(results))
                new_res = SheetResult(
                    config=sheet_config,
                    index=len(results) + 1,
                    label=sheet_label,
                    placed_parts=[PlacedPart(p.name, final_x, final_y, p.width_mm, p.height_mm, rotated)],
                    total_parts_area_mm2=p.area_mm2
                )
                
                results.append(new_res)
                color_packers.setdefault(color, []).append((packer, new_res))

    return results


def export_sheets(
    project_dir: Path,
    sheets_results: list[SheetResult],
    placement_config: PlacementConfig
) -> None:
    """Export the placement results as DXF files in the 'sheets/' directory."""
    sheets_dir = project_dir / "sheets"
    sheets_dir.mkdir(parents=True, exist_ok=True)
    
    # Clear existing files in sheets directory
    for f in sheets_dir.glob("*.dxf"):
        try:
            f.unlink()
        except OSError:
            pass

    parts_dir = project_dir / "parts"
    overlays_dir = project_dir / "overlays"

    for res in sheets_results:
        filename = f"sheet_{res.label}_{res.config.name}.dxf"
        output_path = sheets_dir / filename
        
        doc = ezdxf.new(dxfversion="R2010")
        doc.layers.add(name="cutting", color=7) # White/Black
        doc.layers.add(name="engraving", color=1) # Red
        doc.layers.add(name="sheet_outline", color=8) # Grey
        
        # Draw sheet boundary
        msp = doc.modelspace()
        msp.add_lwpolyline([
            (0, 0), (res.config.width_mm, 0), 
            (res.config.width_mm, res.config.height_mm), 
            (0, res.config.height_mm), (0, 0)
        ], dxfattribs={'layer': 'sheet_outline'})

        # Draw sheet identification label square and text (Top-Left)
        # In CAD: (margin, height - margin - size)
        margin = placement_config.sheet_margin_mm
        l_size = placement_config.label_square_size_mm
        label_x = margin
        label_y = res.config.height_mm - margin - l_size
        
        msp.add_lwpolyline([
            (label_x, label_y), (label_x + l_size, label_y),
            (label_x + l_size, label_y + l_size),
            (label_x, label_y + l_size), (label_x, label_y)
        ], dxfattribs={'layer': 'engraving'})
        
        # Center text inside square
        text = msp.add_text(
            res.label, 
            dxfattribs={
                'layer': 'engraving',
                'height': l_size * 0.4,
                'halign': 1, # CENTER
                'valign': 2, # MIDDLE
            }
        )
        text.set_placement((label_x + l_size/2, label_y + l_size/2))

        for part in res.placed_parts:
            # 1. Import Cutting Geometry
            part_path = parts_dir / f"{part.name}.dxf"
            if part_path.exists():
                _import_part_to_sheet(part_path, doc, msp, (part.x_mm, part.y_mm), "cutting", part.rotated, part.width_mm, part.height_mm)
            
            # 2. Import Engraving Geometry (from overlay if exists)
            overlay_path = overlays_dir / f"{part.name}.dxf"
            if overlay_path.exists():
                _import_part_to_sheet(overlay_path, doc, msp, (part.x_mm, part.y_mm), "engraving", part.rotated, part.width_mm, part.height_mm)

        doc.saveas(output_path)
        
        sheet_area = res.config.width_mm * res.config.height_mm
        utilization = (res.total_parts_area_mm2 / sheet_area) * 100 if sheet_area > 0 else 0
        print(f"  Exported sheet: {filename} ({utilization:.1f}% utilized)")


def export_preview_svg(
    project_dir: Path,
    sheets_results: list[SheetResult],
    svg_paths: dict[str, str],
    placement_config: PlacementConfig
) -> None:
    """Generate a single SVG file previewing all sheets in a grid layout."""
    if not sheets_results:
        return

    output_path = project_dir / "sheets" / "preview.svg"
    
    # Grid settings
    cols = 4
    sheet_gap = 50.0
    label_height = 40.0
    
    max_sheet_w = max(res.config.width_mm for res in sheets_results)
    max_sheet_h = max(res.config.height_mm for res in sheets_results)
    
    cell_w = max_sheet_w + sheet_gap
    cell_h = max_sheet_h + label_height + sheet_gap
    
    rows = (len(sheets_results) + cols - 1) // cols
    
    svg_w = cols * cell_w
    svg_h = rows * cell_h
    
    l_size = placement_config.label_square_size_mm
    
    lines = [
        f'<svg width="{svg_w}" height="{svg_h}" viewBox="0 0 {svg_w} {svg_h}" xmlns="http://www.w3.org/2000/svg">',
        '  <rect width="100%" height="100%" fill="#f8f9fa" />',
        '  <style>',
        '    .sheet-bg { fill: white; stroke: #dee2e6; stroke-width: 1; }',
        '    .part-box { fill: #e9ecef; stroke: #adb5bd; stroke-width: 0.5; fill-rule: evenodd; }',
        '    .engraving { fill: none; stroke: #ff4d4d; stroke-width: 0.3; }',
        '    .sheet-label { font-family: sans-serif; font-size: 14px; fill: #495057; }',
        '    .sheet-id-box { fill: none; stroke: #ff0000; stroke-width: 0.5; }',
        f'    .sheet-id-text {{ font-family: sans-serif; font-size: {l_size * 0.4}px; fill: #ff0000; font-weight: bold; text-anchor: middle; dominant-baseline: central; }}',
        '  </style>'
    ]
    
    for i, res in enumerate(sheets_results):
        row = i // cols
        col = i % cols
        
        base_x = col * cell_w + sheet_gap/2
        base_y = row * cell_h + sheet_gap/2
        
        # Sheet boundary
        lines.append(f'  <g transform="translate({base_x}, {base_y})">')
        lines.append(f'    <rect class="sheet-bg" width="{res.config.width_mm}" height="{res.config.height_mm}" />')
        
        # Identification Square and Label (Top-Left)
        margin = placement_config.sheet_margin_mm
        lines.append(f'    <rect class="sheet-id-box" x="{margin}" y="{margin}" width="{l_size}" height="{l_size}" />')
        lines.append(f'    <text class="sheet-id-text" x="{margin + l_size/2}" y="{margin + l_size/2}">{res.label}</text>')

        # Parts
        for part in res.placed_parts:
            ty = res.config.height_mm - part.y_mm
            
            if part.rotated:
                # CAD: translate(x + H, y), rotate 90 CCW.
                # SVG: translate(x + H, SH - y), rotate -90, scale(1, -1).
                transform = f'translate({part.x_mm + part.height_mm}, {ty}) rotate(-90) scale(1, -1)'
            else:
                transform = f'translate({part.x_mm}, {ty}) scale(1, -1)'
            
            path_data = svg_paths.get(part.name, "")
            lines.append(f'    <path class="part-box" d="{path_data}" transform="{transform}" />')
            
            # Add engraving if overlay exists
            overlay_path = project_dir / "overlays" / f"{part.name}.dxf"
            if overlay_path.exists():
                engraving_data = get_dxf_layer_svg_paths(overlay_path, "engraving")
                if engraving_data:
                    lines.append(f'    <path class="engraving" d="{engraving_data}" transform="{transform}" />')
            
        # Label and Color square below
        label_y = res.config.height_mm + 20
        lines.append(f'    <rect x="0" y="{label_y - 12}" width="14" height="14" fill="{res.config.color}" stroke="#333" stroke-width="0.5" />')
        lines.append(f'    <text class="sheet-label" x="20" y="{label_y}">Sheet {res.label}: {res.config.name}</text>')
        
        lines.append('  </g>')
        
    lines.append('</svg>')
    
    with open(output_path, "w") as f:
        f.write("\n".join(lines))
    
    print(f"  Generated preview: {output_path.name}")


def _import_part_to_sheet(
    source_path: Path, 
    target_doc: ezdxf.document.Drawing, 
    target_layout, 
    offset: tuple[float, float],
    target_layer: str,
    rotated: bool,
    orig_w: float,
    orig_h: float
) -> None:
    """Import geometry from source_path and place it at offset in target_layer."""
    try:
        source_doc = ezdxf.readfile(source_path)
        
        # Create a unique block name for this instance
        block_name = f"PART_{uuid.uuid4().hex}"
        block = target_doc.blocks.new(name=block_name)
        
        importer = Importer(source_doc, target_doc)
        importer.import_modelspace(block)
        importer.finalize()
        
        # If it's an overlay, we only want the 'engraving' layer
        if target_layer == "engraving":
            # Use query('*') to get all entities safely
            for entity in block.query("*"):
                dxf = getattr(entity, 'dxf', None)
                if not dxf:
                    continue
                    
                if dxf.layer.lower() != "engraving":
                    block.delete_entity(entity)
                else:
                    dxf.layer = "engraving"
        else:
            # For parts, import everything to 'cutting'
            for entity in block.query("*"):
                dxf = getattr(entity, 'dxf', None)
                if dxf:
                    dxf.layer = "cutting"
        
        # Insert the block at the correct position
        insert_x, insert_y = offset
        rotation = 0
        if rotated:
            rotation = 90
            # Pivot around bottom-left (0,0) of the PART.
            # Rotating CCW 90 deg around (0,0) moves (0,0)->(0,0) and (W,0)->(0,W) and (0,H)->(-H,0).
            # To bring the new bounding box [-H, 0]x[0, W] to [offset_x, offset_x+H]x[offset_y, offset_y+W]:
            # We must insert at (offset_x + H, offset_y).
            insert_x += orig_h
        
        target_layout.add_blockref(block_name, insert=(insert_x, insert_y), dxfattribs={'rotation': rotation})
        
    except Exception as e:
        print(f"    Warning: Failed to import {source_path.name}: {e}")

def _get_block_width_height(block) -> tuple[float, float]:
    """Estimate block width and height from its entities."""
    from ezdxf import bbox
    cache = bbox.Cache()
    box = bbox.extents(block, cache=cache)
    if box.is_empty:
        return 0, 0
    return box.size.x, box.size.y
