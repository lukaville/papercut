import ezdxf
from ezdxf.addons.importer import Importer
from pathlib import Path
import sys
import uuid
from models import Part, SheetConfig, PlacementConfig, SheetResult, PlacedPart

def index_to_letters(n: int) -> str:
    """Convert a 0-indexed integer to spreadsheet letters (A, B, C, ..., AA, AB)."""
    letters = ""
    n += 1
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters

def place_parts(
    parts: list[Part],
    sheets_config: list[SheetConfig],
    placement_config: PlacementConfig
) -> list[SheetResult]:
    """Place parts on sheets using a Shelf Packing algorithm (NFDH).
    
    Groups parts by color and matches them to sheets of the same color.
    Throws a ValueError if any parts have a color not defined in the sheets configuration.
    """
    if not parts:
        return []

    # Normalize sheet colors for comparison (e.g. #000 -> #000000)
    def normalize_hex(h: str) -> str:
        h = h.lower().lstrip('#')
        if len(h) == 3:
            h = ''.join(c*2 for c in h)
        return '#' + h

    sheet_by_color = {}
    for s in sheets_config:
        color = normalize_hex(s.color)
        sheet_by_color.setdefault(color, []).append(s)

    # Group parts by color
    parts_by_color = {}
    for p in parts:
        color_hex = p.color.hex if p.color else "#000000"
        color = normalize_hex(color_hex)
        parts_by_color.setdefault(color, []).append(p)

    # Check for missing colors
    missing_colors = []
    for color in parts_by_color:
        if color not in sheet_by_color:
            missing_colors.append(color)

    if missing_colors:
        error_msg = "Configuration Error: No sheets found for the following part colors:\n"
        for color in missing_colors:
            affected_parts = [p.name for p in parts_by_color[color]]
            # De-duplicate names if needed, though they should be unique in this context
            unique_affected = sorted(list(set(affected_parts)))
            parts_str = ", ".join(unique_affected)
            error_msg += f"  - {color} (Parts: {parts_str})\n"
        
        error_msg += "\nPlease add them to your 'sheets' configuration in project.yaml:\n\n"
        error_msg += "sheets:\n"
        for color in missing_colors:
            error_msg += f"  - color: \"{color}\"\n"
            error_msg += f"    name: \"custom_{color.lstrip('#')}\"\n"
            error_msg += "    width_mm: 210\n"
            error_msg += "    height_mm: 297\n"
        raise ValueError(error_msg)

    results = []

    # Sort colors to ensure deterministic sheet numbering across runs
    sorted_colors = sorted(parts_by_color.keys())

    for color in sorted_colors:
        color_parts = parts_by_color[color]
        available_sheets = sheet_by_color[color]
        
        # Track all parts that need to be placed for this color
        to_place = []
        for p in sorted(color_parts, key=lambda p: p.height_mm, reverse=True):
            for _ in range(p.count):
                to_place.append((p.name, p.width_mm, p.height_mm))

        # Use the first available sheet type for this color
        current_sheet_config = available_sheets[0]
        
        while to_place:
            # Reserve space for the sheet label square in the top-left
            # CAD: (margin, height - margin - size)
            margin = placement_config.sheet_margin_mm
            l_size = placement_config.label_square_size_mm
            label_x = margin
            label_y = current_sheet_config.height_mm - margin - l_size
            
            label_placeholder = PlacedPart("__LABEL__", label_x, label_y, l_size, l_size)
            
            placed_on_this_sheet = [label_placeholder]
            total_area_on_sheet = l_size * l_size
            
            # Packing state for current sheet
            p_margin = placement_config.part_margin_mm
            
            available_w = current_sheet_config.width_mm - 2 * margin
            available_h = current_sheet_config.height_mm - 2 * margin
            
            cursor_x = margin
            cursor_y = margin
            shelf_height = 0
            
            still_to_place = []
            
            # Use dict for quick area lookup
            area_map = {p.name: p.area_mm2 for p in color_parts}

            for name, w, h in to_place:
                # Try original orientation
                fits_orig = (cursor_x + w <= margin + available_w) and (cursor_y + h <= margin + available_h)
                # Try rotated orientation (90 degrees)
                fits_rot = (cursor_x + h <= margin + available_w) and (cursor_y + w <= margin + available_h)
                
                # If it doesn't fit horizontally on current shelf, try starting new shelf
                if not fits_orig and not fits_rot:
                    # New shelf
                    temp_cursor_x = margin
                    temp_cursor_y = cursor_y + shelf_height + p_margin
                    
                    # Recalculate fit on new shelf
                    fits_orig = (temp_cursor_x + w <= margin + available_w) and (temp_cursor_y + h <= margin + available_h)
                    fits_rot = (temp_cursor_x + h <= margin + available_w) and (temp_cursor_y + w <= margin + available_h)
                    
                    if fits_orig or fits_rot:
                        cursor_x = temp_cursor_x
                        cursor_y = temp_cursor_y
                        shelf_height = 0 
                    else:
                        # Still doesn't fit on new shelf
                        still_to_place.append((name, w, h))
                        continue

                # Place it
                new_part = None
                if fits_orig:
                    new_part = PlacedPart(name, cursor_x, cursor_y, w, h, rotated=False)
                elif fits_rot:
                    new_part = PlacedPart(name, cursor_x, cursor_y, h, w, rotated=True)

                if new_part:
                    # Check for overlaps with existing parts on this sheet (including the label)
                    overlap = False
                    for existing in placed_on_this_sheet:
                        if (new_part.x_mm < existing.x_mm + existing.width_mm + p_margin and
                            existing.x_mm < new_part.x_mm + new_part.width_mm + p_margin and
                            new_part.y_mm < existing.y_mm + existing.height_mm + p_margin and
                            existing.y_mm < new_part.y_mm + new_part.height_mm + p_margin):
                            overlap = True
                            break
                    
                    if overlap:
                        # Try to move to next shelf or skip if it overlaps with the reserved label area
                        # For shelf packing, we just skip it for this sheet and let it go to still_to_place
                        still_to_place.append((name, w, h))
                        continue
                    
                    # If we placed it, update cursor
                    if not new_part.rotated:
                        cursor_x += w + p_margin
                        shelf_height = max(shelf_height, h)
                    else:
                        cursor_x += h + p_margin
                        shelf_height = max(shelf_height, w)
                        
                    placed_on_this_sheet.append(new_part)
                    total_area_on_sheet += area_map[name]
            
            sheet_index = len(results) + 1
            sheet_label = index_to_letters(len(results))
            
            results.append(SheetResult(
                config=current_sheet_config,
                index=sheet_index,
                label=sheet_label,
                placed_parts=[p for p in placed_on_this_sheet if p.name != "__LABEL__"],
                total_parts_area_mm2=total_area_on_sheet - (l_size * l_size)
            ))
            
            if len(to_place) == len(still_to_place):
                # No progress made
                name, w, h = to_place[0]
                raise ValueError(
                    f"Error: Part '{name}' ({w:.1f}x{h:.1f} mm) is too large to fit on sheet "
                    f"'{current_sheet_config.name}' ({current_sheet_config.width_mm:.1f}x{current_sheet_config.height_mm:.1f} mm)."
                )

            to_place = still_to_place

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
        # halign=1 (CENTER), valign=2 (MIDDLE)
        text = msp.add_text(
            res.label, 
            dxfattribs={
                'layer': 'engraving',
                'height': l_size * 0.4, # 40% of square size
                'halign': 1, # CENTER
                'valign': 2, # MIDDLE
                'style': 'OpenSans'
            }
        )
        text.set_placement((label_x + l_size/2, label_y + l_size/2))

        for part in res.placed_parts:
            # For rotated parts, part.width_mm is the original height and part.height_mm is the original width
            orig_w = part.height_mm if part.rotated else part.width_mm
            orig_h = part.width_mm if part.rotated else part.height_mm
            
            # 1. Import Cutting Geometry
            part_path = parts_dir / f"{part.name}.dxf"
            if part_path.exists():
                _import_part_to_sheet(part_path, doc, msp, (part.x_mm, part.y_mm), "cutting", part.rotated, orig_w, orig_h)
            
            # 2. Import Engraving Geometry (from overlay if exists)
            overlay_path = overlays_dir / f"{part.name}.dxf"
            if overlay_path.exists():
                _import_part_to_sheet(overlay_path, doc, msp, (part.x_mm, part.y_mm), "engraving", part.rotated, orig_w, orig_h)

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
        '    .part-box { fill: #e9ecef; stroke: #adb5bd; stroke-width: 0.5; }',
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
        # CAD (margin, height - margin - size) -> SVG (margin, margin)
        margin = placement_config.sheet_margin_mm
        lines.append(f'    <rect class="sheet-id-box" x="{margin}" y="{margin}" width="{l_size}" height="{l_size}" />')
        lines.append(f'    <text class="sheet-id-text" x="{margin + l_size/2}" y="{margin + l_size/2}">{res.label}</text>')

        # Parts (using actual profiles)
        for part in res.placed_parts:
            # CAD to SVG mapping:
            # 1. CAD (x, y) bottom-left -> SVG (x, SH - y) bottom-edge
            # 2. Path is Y-up, so scale(1, -1) makes it Y-down from that point.
            ty = res.config.height_mm - part.y_mm
            
            if part.rotated:
                # CAD: Insert at (x+h, y), Rotate 90 CCW
                # SVG: translate(x+h, sh-y) rotate(-90) scale(1, -1)
                transform = f'translate({part.x_mm + part.width_mm}, {ty}) rotate(-90) scale(1, -1)'
            else:
                # CAD: Insert at (x, y)
                # SVG: translate(x, sh-y) scale(1, -1)
                transform = f'translate({part.x_mm}, {ty}) scale(1, -1)'
            
            path_data = svg_paths.get(part.name, "")
            lines.append(f'    <path class="part-box" d="{path_data}" transform="{transform}" />')
            
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
