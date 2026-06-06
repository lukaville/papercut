"""Part name resolution.

Resolves a unique, stable file name for every deduplicated part group. These
names are the canonical 3D part identity used throughout the pipeline and are
the anchor the manual-builder relies on (never sheet labels, which are
reassigned every run).
"""

import re
from collections import Counter
from typing import Optional

from models import Color, PartGroup, ProjectConfig


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

        # Ensure global uniqueness.
        # _extras parts may intentionally have multiple distinct geometries under
        # the same CAD name — resolve silently with a numeric suffix.
        # For all other parts a conflict indicates a real CAD naming problem.
        if candidate in used_names:
            if base.endswith("_extras"):
                suffix = 2
                while f"{candidate}_{suffix}" in used_names:
                    suffix += 1
                candidate = f"{candidate}_{suffix}"
            else:
                conflicting_groups = [g.names for g, name, _, _ in resolved if name == candidate]
                raise ValueError(
                    f"Naming Conflict: Multiple different part geometries share the name '{candidate}'.\n"
                    f"Conflicting groups names: {group.names} vs {conflicting_groups}\n"
                    f"Please rename parts in the CAD model to ensure each unique geometry has a unique name."
                )
        used_names.add(candidate)

        resolved.append((group, candidate, base, False))

    return resolved
