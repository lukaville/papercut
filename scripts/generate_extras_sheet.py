#!/usr/bin/env python3
"""Generate a PNG sheet of randomly composed elements from layered templates.

Given a directory containing layered template PNGs (e.g. ``small_window_elements``)
and a ``config.yaml`` describing the grid, item size and layers, this script
composes one random item per grid cell and arranges them into a single sheet.

Each template file is grouped into a layer by the layer name embedded in its
file name, e.g. ``_0062_background_5.png`` -> layer ``background``. For every
item, the configured layers are composited bottom-to-top; each layer is included
with its configured probability, picking a random variant when included.

Optional ``constraints`` express relationships between layers: each constraint
picks one weighted combination per item and overrides the per-layer chance for
the layers it governs (e.g. always have either a background or curtains).

The randomization is seeded so the output is fully reproducible.

Usage:
    python generate_extras_sheet.py <directory> [--output sheet.png] [--seed N]
"""

import argparse
import random
import re
import sys
from pathlib import Path

import yaml
from PIL import Image, ImageDraw

# `_0035_curtains_15.png` -> layer "curtains"; `_0014_windowsill.png` -> "windowsill"
_PREFIX_RE = re.compile(r"^_\d+_")
_SUFFIX_RE = re.compile(r"_\d+$")


def layer_name_for(path: Path) -> str:
    """Extract the layer name from a template file name."""
    stem = _PREFIX_RE.sub("", path.stem)
    return _SUFFIX_RE.sub("", stem)


def group_by_layer(directory: Path) -> dict[str, list[Path]]:
    """Return a mapping of layer name -> sorted list of template files."""
    groups: dict[str, list[Path]] = {}
    for path in sorted(directory.glob("*.png")):
        # Only consider files following the `_NNNN_<layer>[_<index>]` convention,
        # so stray PNGs (e.g. a previously generated sheet.png) are ignored.
        if not _PREFIX_RE.match(path.stem):
            continue
        groups.setdefault(layer_name_for(path), []).append(path)
    return groups


def load_config(directory: Path) -> dict:
    config_path = directory / "config.yaml"
    if not config_path.exists():
        sys.exit(f"error: no config.yaml found in {directory}")
    with config_path.open() as f:
        return yaml.safe_load(f)


def resolve_constraints(
    constraints: list[dict], rng: random.Random
) -> tuple[set[str], set[str]]:
    """Pick one weighted combination per constraint.

    Returns (forced_on, governed): ``forced_on`` are layers turned on by the
    chosen combinations, ``governed`` are all layers any constraint controls
    (those not forced on must stay off, ignoring their per-layer chance).
    """
    forced_on: set[str] = set()
    governed: set[str] = set()
    for constraint in constraints:
        combinations = constraint["combinations"]
        weights = [float(c.get("weight", 1.0)) for c in combinations]
        chosen = rng.choices(combinations, weights=weights, k=1)[0]
        for combo in combinations:
            governed.update(combo["include"])
        forced_on.update(chosen["include"])
    return forced_on, governed


def compose_item(
    size: tuple[int, int],
    layers: list[dict],
    groups: dict[str, list[Path]],
    cache: dict[Path, Image.Image],
    rng: random.Random,
    constraints: list[dict],
) -> Image.Image:
    """Compose a single item by stacking layers bottom-to-top."""
    forced_on, governed = resolve_constraints(constraints, rng)
    item = Image.new("RGBA", size, (0, 0, 0, 0))
    for layer in layers:
        name = layer["name"]
        chance = float(layer.get("chance", 1.0))
        variants = groups.get(name)
        if not variants:
            continue
        if name in governed:
            if name not in forced_on:
                continue
        elif rng.random() > chance:
            continue
        choice = rng.choice(variants)
        if choice not in cache:
            img = Image.open(choice).convert("RGBA")
            if img.size != size:
                img = img.resize(size, Image.LANCZOS)
            cache[choice] = img
        
        layer_img = cache[choice]
        if layer.get("flip", False) and rng.random() < 0.5:
            layer_img = layer_img.transpose(Image.FLIP_LEFT_RIGHT)
        item.alpha_composite(layer_img)
    return item


def draw_cut_lines(
    canvas: Image.Image,
    cols: int,
    rows: int,
    item_size: tuple[int, int],
    margin: int,
    cut_lines: dict,
) -> None:
    """Draw the grid cut lines onto ``canvas`` (which already includes margins).

    Lines run the full extent of the canvas, so they reach ``margin`` px past the
    item area on every side. Drawn on a separate overlay so the configured
    opacity blends correctly over both items and the transparent margin.
    """
    width = int(cut_lines.get("width", 2))
    opacity = float(cut_lines.get("opacity", 0.8))
    color = tuple(cut_lines.get("color", [0, 0, 0])) + (round(opacity * 255),)

    iw, ih = item_size
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    for col in range(cols + 1):
        x = margin + col * iw
        draw.line([(x, 0), (x, canvas.height)], fill=color, width=width)
    for row in range(rows + 1):
        y = margin + row * ih
        draw.line([(0, y), (canvas.width, y)], fill=color, width=width)

    canvas.alpha_composite(overlay)


def generate_sheet(
    directory: Path,
    output: Path,
    seed_override: int | None = None
) -> None:
    config = load_config(directory)
    grid = config["grid"]
    cols, rows = int(grid["cols"]), int(grid["rows"])
    item_size = (int(config["item_size"]["width"]), int(config["item_size"]["height"]))
    layers = config.get("layers", [])
    constraints = config.get("constraints", [])
    cut_lines = config.get("cut_lines", {})

    seed = seed_override if seed_override is not None else config.get("seed", 0)
    rng = random.Random(seed)

    groups = group_by_layer(directory)
    if not groups:
        print(f"Warning: no template PNGs found in {directory}, skipping.")
        return

    print(f"Found layers: {', '.join(f'{k} ({len(v)})' for k, v in groups.items())}")
    for layer in layers:
        name = layer["name"]
        if name not in groups:
            print(f"Warning: Configured layer {name!r} was not found in template files.")

    iw, ih = item_size
    margin = int(cut_lines.get("margin", 0))
    sheet = Image.new("RGBA", (cols * iw + 2 * margin, rows * ih + 2 * margin), (0, 0, 0, 0))
    cache: dict[Path, Image.Image] = {}

    for row in range(rows):
        for col in range(cols):
            item = compose_item(item_size, layers, groups, cache, rng, constraints)
            sheet.alpha_composite(item, (margin + col * iw, margin + row * ih))

    if cut_lines:
        draw_cut_lines(sheet, cols, rows, item_size, margin, cut_lines)

    sheet.save(output)
    print(f"Wrote {cols}x{rows} sheet ({sheet.width}x{sheet.height}) to {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "directory",
        type=Path,
        help="directory with layered template PNGs and a config.yaml",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="output PNG path (default: <directory>/sheet.png)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        help="random seed (overrides the seed from config.yaml)",
    )
    args = parser.parse_args()

    directory: Path = args.directory
    if not directory.is_dir():
        sys.exit(f"error: not a directory: {directory}")

    # Find all config.yaml files recursively
    config_paths = sorted(directory.rglob("config.yaml"))
    if not config_paths:
        sys.exit(f"error: no config.yaml found in {directory}")

    print(f"Found {len(config_paths)} configuration(s) to process.")
    for config_path in config_paths:
        dir_to_process = config_path.parent
        print(f"\nProcessing directory: {dir_to_process}")
        
        if args.output:
            if len(config_paths) == 1:
                output = args.output
            else:
                output = dir_to_process / args.output.name
        else:
            output = dir_to_process / "sheet.png"

        generate_sheet(dir_to_process, output, seed_override=args.seed)


if __name__ == "__main__":
    main()
