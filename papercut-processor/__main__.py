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
from deduplicator import deduplicate, PartGroup
from dxf_exporter import export_part_dxf
from clash_detection import check_intersections
from overlay_manager import manage_overlays, get_engraving_entities
from placer import place_parts, export_sheets, export_preview_svg
from naming import resolve_names
from manual_exporter import export_manual_model
from models import Part, ProjectConfig, PartInstance, Color, EngravingInfo
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



def _opposite_side(side: str) -> str:
    return "bottom" if side == "top" else "top"


def _group_flip(group: "PartGroup", part_configs: dict) -> tuple[bool, bool]:
    """Resolve the manufacturing flip for a group from its source CAD names.

    Returns (flip_horizontal, flip_vertical). A group's instances share a
    compatible name, so any matching config entry applies to the whole group.
    """
    for name in group.names:
        cfg = part_configs.get(name)
        if cfg:
            return cfg.flip_horizontal, cfg.flip_vertical
    return False, False


def _find_overlay_path(project_dir: Path, part_name: str, base_name: Optional[str]) -> Optional[Path]:
    """Return the overlay DXF path for a part, or None if not found."""
    overlays_dir = project_dir / "overlays"
    for name in ([part_name, base_name] if base_name else [part_name]):
        p = overlays_dir / f"{name}.dxf"
        if p.exists():
            return p

    engravings_base = project_dir / ".cache" / "engravings"
    if engravings_base.exists():
        for subdir in engravings_base.iterdir():
            if not subdir.is_dir():
                continue
            for name in ([part_name, base_name] if base_name else [part_name]):
                p = subdir / f"{name}.dxf"
                if p.exists():
                    return p
    return None


def _engraving_svg(entities: list, mat) -> str:
    """Return SVG path data for engraving entities after applying the alignment matrix."""
    from ezdxf import path as ezdxf_path
    parts: list[str] = []
    for entity in entities:
        try:
            e_copy = entity.copy()
            e_copy.transform(mat)
            p = ezdxf_path.make_path(e_copy)
            pts = list(p.flattening(distance=0.1))
            if len(pts) < 2:
                continue
            d = f"M {pts[0].x:.2f},{pts[0].y:.2f}"
            for pt in pts[1:]:
                d += f" L {pt.x:.2f},{pt.y:.2f}"
            parts.append(d)
        except Exception:
            continue
    return " ".join(parts)


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
    
    # Per-part cut overrides (mirror the 2D cut), keyed by source CAD name.
    part_configs = config.cut_overrides

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
    # Exclude _extras parts — they may be irregular overlays/stickers that are
    # not representative of the sheet material.
    print("Detecting material thickness ...")
    with Timer("Thickness detection"):
        thickness = detect_thickness([
            inst.solid for inst in all_instances
            if not inst.name.endswith("_extras")
        ])
    print(f"  Detected material thickness: {thickness:.3f} mm")

    # NOTE: import-level part flips (config `import[].parts[name].flip_*`) are a
    # *manufacturing* concern — they mirror the 2D cut profile so a paired
    # directional part is engraved on the correct physical face. They are applied
    # only in the DXF export path (see export_part_dxf below); the 3D geometry
    # used for deduplication and the manual model is left in its true source
    # orientation, so the manual viewer shows parts un-flipped.

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
    
    # Pre-export unique shapes to BREP files for stable multiprocessing.
    # _extras parts are skipped — they are manual-preview-only and need no DXF.
    brep_cache_dir = project_dir / ".cache" / "breps"
    brep_cache_dir.mkdir(parents=True, exist_ok=True)

    extras_group_ids = {
        group.id
        for group, _, base_name, _ in group_names
        if base_name.endswith("_extras")
    }

    group_breps = {}
    with Timer("BREP caching"):
        for group in groups:
            if group.id in extras_group_ids:
                continue
            brep_path = brep_cache_dir / f"group_{group.id}.brep"
            group.canonical.exportBrep(str(brep_path))
            group_breps[group.id] = brep_path

    placement_metadata: list[Part] = []
    svg_paths = {} # Temporary store for preview
    group_dxf_transforms: dict[int, list[float]] = {}  # group.id -> 2D DXF -> local 3D matrix

    kerf_offset = config.kerf.offset_mm if config.kerf.compensation else 0.0

    with Timer("DXF Export"):
        with ProcessPoolExecutor(max_workers=multiprocessing.cpu_count()) as executor:
            future_to_part = {}
            for group, filename, base_name, _ in group_names:
                # Always update instance names — the manual model exporter needs them.
                for inst in all_instances:
                    if inst.group_id == group.id:
                        inst.name = filename

                # _extras: skip DXF export and sheet placement entirely.
                if base_name.endswith("_extras"):
                    continue

                dxf_path = parts_dir / f"{filename}.dxf"
                ref_path = parts_dir / f"{filename}.ref.dxf" if config.kerf.compensation else None

                # Manufacturing flip: mirrors the 2D cut only, not the 3D model.
                flip_h, flip_v = _group_flip(group, part_configs)

                future = executor.submit(
                    export_part_dxf,
                    group_breps[group.id],
                    dxf_path,
                    thickness,
                    kerf_offset,
                    ref_path,
                    flip_h,
                    flip_v,
                )
                future_to_part[future] = (filename, base_name, group)

            for future in as_completed(future_to_part):
                filename, base_name, group = future_to_part[future]
                # No try-except here - let it raise and stop the process if a part fails
                width_mm, height_mm, area, svg_path, dxf_to_local = future.result()
                svg_paths[filename] = svg_path
                group_dxf_transforms[group.id] = dxf_to_local

                opts = config.part_options.get(filename) or config.part_options.get(base_name)
                extra = opts.extra_count if opts else 0

                dim_str = f"{width_mm:.1f} × {height_mm:.1f} × {thickness:.1f}"
                placement_metadata.append(Part(
                    name=filename,
                    base_name=base_name,
                    width_mm=width_mm,
                    height_mm=height_mm,
                    area_mm2=area,
                    count=group.count,
                    color=group.color,
                    group_id=group.id,
                    extra_count=extra,
                ))

                color_str = "Default"
                if group.color:
                    c = group.color
                    color_str = f"({c.r:.2f}, {c.g:.2f}, {c.b:.2f}, {c.a:.2f})"
                count_str = f"{group.count}×"
                if extra > 0:
                    count_str += f" (+{extra})"
                print(f"  {filename:<26} {count_str:>12}   {dim_str:<27} {color_str}")

    dxf_count = len(groups) - len(extras_group_ids)
    print()
    print(f"Done. {dxf_count} DXF file(s) written to {parts_dir}", end="")
    if extras_group_ids:
        print(f"  ({len(extras_group_ids)} _extras group(s) kept for manual model only)", end="")
    print()

    # Step 5.5: Resolve engraving info for each part group
    # Find which overlay file belongs to each group and determine engraving side
    # (top or bottom face) by examining which orientation the alignment search chose.
    print()
    print("Resolving engravings ...")
    # Instance ordinals whose side is flipped relative to the part side, keyed by
    # resolved part filename. Consumed by the manual exporter (which assigns the
    # ordinals the ranges refer to).
    engraving_flip_instances: dict[str, set] = {}
    with Timer("Engraving resolution"):
        for group, filename, base_name, _ in group_names:
            if base_name.endswith("_extras"):
                continue
            overlay_path = _find_overlay_path(project_dir, filename, base_name)
            if not overlay_path:
                continue
            part_path = parts_dir / f"{filename}.dxf"
            ref_path = part_path.with_suffix(".ref.dxf")
            match_path = ref_path if ref_path.exists() else part_path
            if not match_path.exists():
                continue

            e_config = config.engraving_overrides.get(filename) or config.engraving_overrides.get(base_name)
            flip_h = e_config.flip_horizontal if e_config else False
            flip_v = e_config.flip_vertical if e_config else False

            try:
                engravings, align_mat, flip_x_used, rotation_deg = get_engraving_entities(
                    overlay_path, match_path, flip_h, flip_v
                )
                # flip_h/flip_v now mirror the artwork in-plane after alignment, so
                # flip_x_used reflects only the overlay's intrinsic orientation —
                # i.e. it is already flip-free. The face is this base plus explicit
                # flip_side / per-instance overrides.
                auto_side = "bottom" if flip_x_used else "top"
                # `flip_side: true` inverts the auto-detected side for the whole part.
                flip_side = bool(e_config.flip_side) if e_config else False
                side = _opposite_side(auto_side) if flip_side else auto_side
                svg = _engraving_svg(engravings, align_mat)
                group.engraving = EngravingInfo(
                    side=side,
                    svg=svg,
                    transform=group_dxf_transforms.get(group.id),
                    auto_side=auto_side,
                    flip_horizontal=flip_h,
                    flip_vertical=flip_v,
                )
                if e_config and e_config.flip_side_instances:
                    engraving_flip_instances[filename] = e_config.flip_side_instances

                note = " (flip_side)" if flip_side else ""
                if e_config and e_config.flip_side_instances:
                    note += " (+per-instance flips)"
                print(f"  {filename}: engraving on {side} face{note}")
            except ValueError as e:
                print(f"  Warning: Could not resolve engraving for '{filename}': {e}")

    # Step 6: Manage Overlays
    overlays_dir = project_dir / "overlays"
    if overlays_dir.is_dir():
        print(f"Managing overlays in {overlays_dir} ...")
        with Timer("Overlay management"):
            manage_overlays(project_dir, config.engraving_overrides)

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
                suffix = "+" if pp.is_spare else ""
                full_id = f"{res.label}{pp.part_id}{suffix}"
                mapping.setdefault(pp.name, set()).add(full_id)
        
        # Natural sort for IDs (A1, A2, A10)
        def natural_key(s):
            return [int(text) if text.isdigit() else text.lower()
                    for text in re.split(r'(\d+)', s)]

        for part_name in sorted(mapping.keys()):
            ids = sorted(list(mapping[part_name]), key=natural_key)
            print(f"  {part_name:<30} -> {', '.join(ids)}")

    # Step 8: Export the 3D model consumed by the manual-builder web app.
    print()
    print("Exporting manual model ...")
    with Timer("Manual model export"):
        model_path = export_manual_model(
            project_dir,
            all_instances,
            groups,
            sheets_results,
            thickness_mm=thickness,
            engraving_flip_instances=engraving_flip_instances,
        )
    print(f"  Manual model written to: {model_path}")


if __name__ == "__main__":
    main()
