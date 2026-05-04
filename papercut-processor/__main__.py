"""Main entry point for the papercut processor."""

import sys
import os
import re
from pathlib import Path

import cadquery as cq
from OCP.gp import gp_Pnt, gp_Ax2, gp_Dir, gp_Trsf
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform

from config import load_config
from step_reader import load_step
from thickness import detect_thickness
from deduplicator import deduplicate, PartGroup, _mirror_solid
from dxf_exporter import export_part_dxf
from clash_detection import check_intersections
from overlay_manager import manage_overlays
from placer import place_parts, export_sheets, export_preview_svg
from models import Part, ProjectConfig


def resolve_names(groups: list[PartGroup]) -> list[tuple[PartGroup, str, bool]]:
    """Resolve a unique filename for each part group and determine flipping."""
    resolved = []
    used_names = set()
    
    for i, group in enumerate(groups):
        # 1. Try to find a meaningful name
        candidate = None
        meaningful_names = [n for n in group.names if not re.match(r"Part \d+", n)]
        
        if len(meaningful_names) == 0:
            # All names are 'Part N', pick the one with lowest N
            part_numbers = []
            for n in group.names:
                m = re.match(r"Part (\d+)", n)
                if m:
                    part_numbers.append(int(m.group(1)))
            
            if part_numbers:
                candidate = f"part_{min(part_numbers)}"
            else:
                candidate = f"part_{i}"
        elif len(meaningful_names) == 1:
            candidate = meaningful_names[0].lower().replace(" ", "_")
        else:
            # Multiple meaningful names - check if they match after normalization
            normalized = {n.lower().replace(" ", "_") for n in meaningful_names}
            if len(normalized) == 1:
                candidate = list(normalized)[0]
            else:
                # Conflict!
                # We'll just pick one and the uniqueness check will handle it
                candidate = list(normalized)[0]
        
        # Ensure candidate is alphanumeric-ish
        candidate = "".join(c if c.isalnum() or c in "_-" else "_" for c in candidate)
        
        # Ensure global uniqueness - FAIL on conflict as requested
        if candidate in used_names:
            # Find which groups have this name
            conflicting_groups = [g.names for g, name, _ in resolved if name == candidate]
            raise ValueError(
                f"Naming Conflict: Multiple different part geometries share the name '{candidate}'.\n"
                f"Conflicting groups names: {group.names} vs {conflicting_groups}\n"
                f"Please rename parts in the CAD model to ensure each unique geometry has a unique name."
            )
        used_names.add(candidate)
        
        resolved.append((group, candidate, False))
        
    return resolved


def main():
    if len(sys.argv) < 2:
        print("Usage: ./process <project_directory>")
        sys.exit(1)

    project_dir = Path(sys.argv[1]).resolve()
    if not project_dir.is_dir():
        print(f"Error: {project_dir} is not a directory")
        sys.exit(1)

    # Step 0: Load project configuration
    config = load_config(project_dir)
    
    # Map of part names to their config for quick lookup
    part_configs = {}
    for imp in config.imports:
        for name, p_config in imp.parts.items():
            part_configs[name] = p_config

    # Step 1: Load all solids from imported files
    all_named_solids = []
    for imp in config.imports:
        step_path = project_dir / imp.file
        print(f"Loading {step_path} ...")
        solids = load_step(step_path)
        all_named_solids.extend(solids)

    if not all_named_solids:
        print("No parts found in STEP files.")
        return

    print(f"  Found {len(all_named_solids)} solid(s)")

    # Step 1.5: Check for intersections (clashes)
    print("Checking for volumetric intersections (clash detection) ...")
    try:
        check_intersections(all_named_solids)
        print("  No intersections found (tolerance: 0.0001 mm³).")
    except ValueError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

    # Step 2: Detect material thickness
    print("Detecting material thickness ...")
    thickness = detect_thickness([s for s, _, _ in all_named_solids])
    print(f"  Detected material thickness: {thickness:.3f} mm")

    # Step 2.5: Apply flips based on configuration
    print("Applying part flips ...")
    transformed_solids = []
    for solid, name, color in all_named_solids:
        if name in part_configs:
            p_config = part_configs[name]
            if p_config.flip_horizontal or p_config.flip_vertical:
                # Find thickness axis for this specific instance
                bb = solid.BoundingBox()
                dims = [("X", bb.xlen), ("Y", bb.ylen), ("Z", bb.zlen)]
                # Find the dimension closest to 'thickness' detected in Step 2
                thickness_axis = min(dims, key=lambda d: abs(d[1] - thickness))[0]
                
                # Map Horizontal/Vertical to CAD axes based on thickness orientation
                if thickness_axis == "Z":
                    h_axis, v_axis = "X", "Y"
                elif thickness_axis == "X":
                    h_axis, v_axis = "Y", "Z"
                else: # Y
                    h_axis, v_axis = "X", "Z"
                
                if p_config.flip_horizontal:
                    solid = _mirror_solid(solid, h_axis)
                if p_config.flip_vertical:
                    solid = _mirror_solid(solid, v_axis)
        transformed_solids.append((solid, name, color))
    all_named_solids = transformed_solids

    # Step 3: Deduplicate union of all solids
    print("Deduplicating union of all parts ...")
    groups = deduplicate(all_named_solids)
    print(f"  Found {len(groups)} unique part(s)")

    # Step 4: Resolve names
    group_names = resolve_names(groups)

    # Step 5: Export DXF files
    parts_dir = project_dir / "parts"
    parts_dir.mkdir(parents=True, exist_ok=True)

    # Clear existing DXF files to prevent stale leftovers from previous runs
    for f in parts_dir.glob("*.dxf"):
        try:
            f.unlink()
        except OSError:
            pass

    print(f"Exporting DXF files to {parts_dir} ...")
    print()
    print(f"  {'Filename':<32} {'Count':>5}   {'Dimensions (bbox)':<27} {'Color (RGBA)'}")
    print(f"  {'─' * 24:32} {'─' * 6:>5}   {'─' * 25:27} {'─' * 15}")

    placement_metadata = []
    svg_paths = {} # Temporary store for preview

    for group, filename, _ in group_names:
        dxf_path = parts_dir / f"{filename}.dxf"
        
        shape_to_export = group.canonical

        # Export and get the compensated dimensions and SVG path
        kerf_offset = config.kerf.offset_mm if config.kerf.compensation else 0.0
        ref_path = parts_dir / f"{filename}.ref.dxf" if config.kerf.compensation else None
        
        width_mm, height_mm, area, svg_path = export_part_dxf(shape_to_export, dxf_path, thickness, kerf_offset, ref_path)
        svg_paths[filename] = svg_path

        # Use the compensated dimensions for reporting
        # For Z dimension, we still use material thickness
        dim_str = f"{width_mm:.1f} × {height_mm:.1f} × {thickness:.1f}"
        
        # Store for placement
        placement_metadata.append(Part(
            name=filename,
            width_mm=width_mm,
            height_mm=height_mm,
            area_mm2=area,
            count=group.count,
            color=group.color
        ))
        
        # Get color info for reporting
        color_str = "Default"
        if group.color:
            c = group.color
            color_str = f"({c.r:.2f}, {c.g:.2f}, {c.b:.2f}, {c.a:.2f})"
            
        print(f"{filename:<26} {group.count:>5}×   {dim_str:<27} {color_str}")

    print()
    print(f"Done. {len(groups)} DXF file(s) written to {parts_dir}")

    # Step 6: Manage Overlays
    overlays_dir = project_dir / "overlays"
    if overlays_dir.is_dir():
        print(f"Managing overlays in {overlays_dir} ...")
        manage_overlays(project_dir, config.overlays)

    # Step 7: Place parts on sheets
    if config.sheets:
        print()
        print(f"Placing parts on sheets in {project_dir / 'sheets'} ...")
        
        sheets_results = place_parts(
            placement_metadata,
            config.sheets,
            config.placement
        )
        
        export_sheets(project_dir, sheets_results, config.placement, config.bridges)
        export_preview_svg(project_dir, sheets_results, svg_paths, config.placement, config.bridges)


if __name__ == "__main__":
    main()
