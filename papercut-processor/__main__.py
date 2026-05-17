"""Main entry point for the papercut processor."""

import sys
import os
import re
from pathlib import Path
from typing import Optional, Any

import cadquery as cq
from OCP.gp import gp_Pnt, gp_Ax2, gp_Dir, gp_Trsf
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform

from config import load_config
from step_reader import load_step
from onshape_client import download_from_onshape, parse_onshape_url, export_engravings
from thickness import detect_thickness
from deduplicator import deduplicate, PartGroup, _mirror_solid
from dxf_exporter import export_part_dxf
from clash_detection import check_intersections
from overlay_manager import manage_overlays
from placer import place_parts, export_sheets, export_preview_svg
from viewer_exporter import export_viewer
from models import Part, ProjectConfig, PartInstance, Color
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing


class Timer:
    def __init__(self, name):
        self.name = name

    def __enter__(self):
        self.start = time.perf_counter()
        return self

    def __exit__(self, *args):
        self.end = time.perf_counter()
        self.duration = self.end - self.start
        print(f"  [{self.name}] took {self.duration:.3f}s")



def get_color_name(color: Optional[Color], config: ProjectConfig) -> str:
    """Find a friendly name for a color from the project config."""
    if not color:
        return ""
    hex_val = color.hex.lower()
    for sheet in config.sheets:
        if sheet.color.lower() == hex_val:
            return sheet.name
    return hex_val.replace("#", "")


def resolve_names(groups: list[PartGroup], config: ProjectConfig) -> list[tuple[PartGroup, str, str, bool]]:
    """Resolve a unique filename for each part group and determine flipping."""
    
    # Pass 1: Determine base names for all groups
    base_names = []
    for i, group in enumerate(groups):
        candidate = None
        meaningful_names = [n for n in group.names if not re.match(r"Part \d+", n)]
        
        if len(meaningful_names) == 0:
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
            normalized = {n.lower().replace(" ", "_") for n in meaningful_names}
            candidate = list(normalized)[0]
        
        # Ensure candidate is alphanumeric-ish
        candidate = "".join(c if c.isalnum() or c in "_-" else "_" for c in candidate)
        base_names.append(candidate)

    # Pass 2: Disambiguate if necessary (multi-pass check for unique names)
    from collections import Counter
    counts = Counter(base_names)
    
    resolved = []
    used_names = set()
    
    for i, group in enumerate(groups):
        base = base_names[i]
        
        # If multiple groups share the same base name, try to disambiguate by color
        if counts[base] > 1:
            color_name = get_color_name(group.color, config)
            if color_name:
                candidate = f"{base}_{color_name}"
            else:
                # Fallback to index if color matching fails
                candidate = f"{base}_{i}"
        else:
            candidate = base
        
        # Ensure global uniqueness - FAIL on conflict as requested
        if candidate in used_names:
            # Find which groups have this name
            conflicting_groups = [g.names for g, name, _, _ in resolved if name == candidate]
            raise ValueError(
                f"Naming Conflict: Multiple different part geometries share the name '{candidate}'.\n"
                f"Conflicting groups names: {group.names} vs {conflicting_groups}\n"
                f"Please rename parts in the CAD model to ensure each unique geometry has a unique name."
            )
        used_names.add(candidate)
        
        resolved.append((group, candidate, base, False))
        
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

    # Step 1: Load all solids and instances from imported files
    all_instances = []
    for imp in config.imports:
        if imp.file.startswith("http://") or imp.file.startswith("https://"):
            # It's a URL
            did, wvm, wvmid, eid = parse_onshape_url(imp.file)
            cache_dir = project_dir / ".cache"
            cache_file = cache_dir / f"onshape_{did}_{wvm}_{wvmid}_{eid}.step"
            
            if cache_file.exists():
                print(f"Using cached file {cache_file} ...")
                step_path = cache_file
            else:
                print(f"Downloading from OnShape: {imp.file} ...")
                download_from_onshape(imp.file, str(cache_file))
                step_path = cache_file
                
                # Export engravings
                engravings_dir = project_dir / ".cache" / "engravings" / f"{did}_{eid}"
                with Timer(f"Exporting engravings to {engravings_dir}"):
                    export_engravings(imp.file, str(engravings_dir))


        else:
            step_path = project_dir / imp.file
            
        print(f"Loading {step_path} ...")
        with Timer(f"Load {step_path.name}"):
            instances = load_step(step_path)
            all_instances.extend(instances)

    if not all_instances:
        print("No parts found in STEP files.")
        return

    print(f"  Found {len(all_instances)} instance(s)")

    # Step 1.5: Check for intersections (clashes)
    print("Checking for volumetric intersections (clash detection) ...")
    with Timer("Clash detection"):
        try:
            check_intersections(all_instances)
            print("  No intersections found (tolerance: 0.0001 mm³).")
        except ValueError as e:
            print(str(e), file=sys.stderr)
            sys.exit(1)

    # Step 2: Detect material thickness
    print("Detecting material thickness ...")
    with Timer("Thickness detection"):
        thickness = detect_thickness([inst.solid for inst in all_instances])
    print(f"  Detected material thickness: {thickness:.3f} mm")

    # Step 2.5: Apply flips based on configuration
    print("Applying part flips ...")
    for inst in all_instances:
        if inst.name in part_configs:
            p_config = part_configs[inst.name]
            if p_config.flip_horizontal or p_config.flip_vertical:
                # Find thickness axis for this specific instance
                bb = inst.solid.BoundingBox()
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
                    inst.solid = _mirror_solid(inst.solid, h_axis)
                if p_config.flip_vertical:
                    inst.solid = _mirror_solid(inst.solid, v_axis)

    # Step 3: Deduplicate union of all solids
    print("Deduplicating union of all parts ...")
    with Timer("Deduplication"):
        groups = deduplicate(all_instances)
    print(f"  Found {len(groups)} unique part(s)")

    # Step 4: Resolve names
    group_names = resolve_names(groups, config)

    # Step 5: Export DXF files
    parts_dir = project_dir / "parts"
    parts_dir.mkdir(parents=True, exist_ok=True)

    # Clear existing DXF files
    for f in parts_dir.glob("*.dxf"):
        try:
            f.unlink()
        except OSError:
            pass

    print(f"Exporting DXF files to {parts_dir} ...")
    print()
    print(f"  {'Filename':<32} {'Count':>5}   {'Dimensions (bbox)':<27} {'Color (RGBA)'}")
    print(f"  {'─' * 24:32} {'─' * 6:>5}   {'─' * 25:27} {'─' * 15}")
    
    # Pre-export unique shapes to BREP files for stable multiprocessing
    brep_cache_dir = project_dir / ".cache" / "breps"
    brep_cache_dir.mkdir(parents=True, exist_ok=True)
    
    group_breps = {}
    with Timer("BREP caching"):
        for group in groups:
            brep_path = brep_cache_dir / f"group_{group.id}.brep"
            group.canonical.exportBrep(str(brep_path))
            group_breps[group.id] = brep_path

    placement_metadata: list[Part] = []
    svg_paths = {} # Temporary store for preview

    kerf_offset = config.kerf.offset_mm if config.kerf.compensation else 0.0
    
    with Timer("DXF Export"):
        with ProcessPoolExecutor(max_workers=multiprocessing.cpu_count()) as executor:
            future_to_part = {}
            for group, filename, base_name, _ in group_names:
                # Update instances in this group to have the resolved filename
                for inst in all_instances:
                    if inst.group_id == group.id:
                        inst.name = filename

                dxf_path = parts_dir / f"{filename}.dxf"
                ref_path = parts_dir / f"{filename}.ref.dxf" if config.kerf.compensation else None
                
                future = executor.submit(
                    export_part_dxf, 
                    group_breps[group.id], 
                    dxf_path, 
                    thickness, 
                    kerf_offset, 
                    ref_path
                )
                future_to_part[future] = (filename, base_name, group)

            for future in as_completed(future_to_part):
                filename, base_name, group = future_to_part[future]
                # No try-except here - let it raise and stop the process if a part fails
                width_mm, height_mm, area, svg_path = future.result()
                svg_paths[filename] = svg_path
                
                dim_str = f"{width_mm:.1f} × {height_mm:.1f} × {thickness:.1f}"
                placement_metadata.append(Part(
                    name=filename,
                    base_name=base_name,
                    width_mm=width_mm,
                    height_mm=height_mm,
                    area_mm2=area,
                    count=group.count,
                    color=group.color,
                    group_id=group.id
                ))
                
                color_str = "Default"
                if group.color:
                    c = group.color
                    color_str = f"({c.r:.2f}, {c.g:.2f}, {c.b:.2f}, {c.a:.2f})"
                print(f"  {filename:<26} {group.count:>5}×   {dim_str:<27} {color_str}")


    print()
    print(f"Done. {len(groups)} DXF file(s) written to {parts_dir}")

    # Step 6: Manage Overlays
    overlays_dir = project_dir / "overlays"
    if overlays_dir.is_dir():
        print(f"Managing overlays in {overlays_dir} ...")
        with Timer("Overlay management"):
            manage_overlays(project_dir, config.overlays)

    # Step 7: Place parts on sheets
    sheets_results = []
    if config.sheets:
        print()
        print(f"Placing parts on sheets in {project_dir / 'sheets'} ...")
        
        with Timer("Part placement"):
            sheets_results = place_parts(
                placement_metadata,
                config.sheets,
                config.placement,
                all_instances
            )
        
        with Timer("Sheet export"):
            export_sheets(project_dir, sheets_results, config.placement, config.bridges)
            export_preview_svg(project_dir, sheets_results, svg_paths, config.placement, config.bridges)

        # Print part ID mapping
        print()
        print("Part ID Mapping:")
        mapping = {}
        for res in sheets_results:
            for pp in res.placed_parts:
                full_id = f"{res.label}{pp.part_id}"
                mapping.setdefault(pp.name, set()).add(full_id)
        
        # Natural sort for IDs (A1, A2, A10)
        def natural_key(s):
            return [int(text) if text.isdigit() else text.lower()
                    for text in re.split(r'(\d+)', s)]

        for part_name in sorted(mapping.keys()):
            ids = sorted(list(mapping[part_name]), key=natural_key)
            print(f"  {part_name:<30} -> {', '.join(ids)}")

    # Step 8: Export 3D Viewer
    with Timer("Viewer export"):
        export_viewer(project_dir, all_instances, groups, sheets_results)


if __name__ == "__main__":
    main()
