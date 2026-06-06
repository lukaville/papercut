"""Standalone, non-destructive regeneration of the manual 3D model.

Reconstructs deduplicated parts, instances and (approximate) sheet labels from a
project's cached STEP and writes only ``[project]/manual/model/``. Unlike
``./process`` it does not touch ``parts/``, ``sheets/`` or ``overlays/``, which
makes it cheap to re-run while iterating on the manual-builder web app.

    PYTHONPATH=papercut-processor python papercut-processor/export_manual.py projects/cut_sample

Onshape imports are only read from the local ``.cache``; run ``./process`` once
first to populate it (this tool never downloads).
"""

import sys
from pathlib import Path

from config import load_config
from step_reader import load_step
from onshape_client import parse_onshape_url
from thickness import detect_thickness
from deduplicator import deduplicate
from naming import resolve_names
from placer import place_parts
from manual_exporter import export_manual_model
from models import Part


def _resolve_step_path(project_dir: Path, file_ref: str) -> Path:
    """Resolve an import entry to a local STEP path, using only the cache."""
    if file_ref.startswith("http://") or file_ref.startswith("https://"):
        did, wvm, wvmid, eid = parse_onshape_url(file_ref)
        cache_file = project_dir / ".cache" / f"onshape_{did}_{wvm}_{wvmid}_{eid}.step"
        if not cache_file.exists():
            raise FileNotFoundError(
                f"Cached STEP not found for {file_ref}.\n"
                f"Expected: {cache_file}\n"
                f"Run `./process {project_dir}` once to populate the cache."
            )
        return cache_file
    return project_dir / file_ref




def _approx_part_dims(group, thickness):
    """Approximate 2D footprint from the bounding box (drops the thinnest axis)."""
    bb = group.canonical.BoundingBox()
    dims = sorted([bb.xlen, bb.ylen, bb.zlen])
    height_mm, width_mm = dims[1], dims[2]
    return width_mm, height_mm


def main():
    if len(sys.argv) < 2:
        print("Usage: python export_manual.py <project_directory>", file=sys.stderr)
        sys.exit(1)

    project_dir = Path(sys.argv[1]).resolve()
    if not project_dir.is_dir():
        print(f"Error: {project_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    config = load_config(project_dir)

    all_instances = []
    for imp in config.imports:
        step_path = _resolve_step_path(project_dir, imp.file)
        print(f"Loading {step_path} ...")
        all_instances.extend(load_step(step_path))

    if not all_instances:
        print("No parts found.", file=sys.stderr)
        sys.exit(1)
    print(f"  Found {len(all_instances)} instance(s)")

    thickness = detect_thickness([inst.solid for inst in all_instances])
    print(f"  Detected thickness: {thickness:.3f} mm")

    # NOTE: cut flips are a 2D-manufacturing concern and intentionally NOT applied
    # to the 3D geometry — the manual model uses the true source orientation.

    groups = deduplicate(all_instances)
    print(f"  Found {len(groups)} unique part(s)")

    # Resolve stable part keys and stamp them onto instances.
    resolved = resolve_names(groups, config)
    placement_metadata = []
    for group, filename, base_name, _ in resolved:
        for inst in all_instances:
            if inst.group_id == group.id:
                inst.name = filename
        width_mm, height_mm = _approx_part_dims(group, thickness)
        placement_metadata.append(Part(
            name=filename,
            base_name=base_name,
            width_mm=width_mm,
            height_mm=height_mm,
            area_mm2=width_mm * height_mm,
            count=group.count,
            color=group.color,
            group_id=group.id,
        ))

    # Approximate sheet placement to assign display labels (best effort).
    sheets_results = []
    if config.sheets:
        try:
            sheets_results = place_parts(
                placement_metadata, config.sheets, config.placement, all_instances
            )
        except Exception as e:  # noqa: BLE001 - labels are non-essential here
            print(f"  Warning: sheet placement skipped ({e}); labels will be empty.")

    model_path = export_manual_model(
        project_dir, all_instances, groups, sheets_results, thickness_mm=thickness
    )
    print(f"Manual model written to: {model_path}")


if __name__ == "__main__":
    main()
