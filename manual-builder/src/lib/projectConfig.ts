/**
 * Read/edit the `engraving_overrides` section of a project's `project.yaml`.
 *
 * Only the engraving keys are touched; the rest of the file (imports, sheets,
 * cut_overrides, comments, formatting) is preserved by editing through the
 * `yaml` Document model.
 */

import { parse, parseDocument } from "yaml";

export type Side = "top" | "bottom";

export interface EngravingOverride {
  flipHorizontal: boolean;
  flipVertical: boolean;
  /** Flip the auto-detected side for the whole part. */
  flipSide: boolean;
  /** Instance ordinals flipped relative to the part's resolved side. */
  flipInstances: number[];
}

export function emptyOverride(): EngravingOverride {
  return { flipHorizontal: false, flipVertical: false, flipSide: false, flipInstances: [] };
}

export function opposite(side: Side): Side {
  return side === "top" ? "bottom" : "top";
}

/**
 * Effective engraving side for one instance.
 *
 * `autoSide` is the flip-free detected face. flip_horizontal/flip_vertical only
 * mirror the artwork in-plane (handled separately) and never change the face —
 * the face is controlled solely by flip_side (whole part) and per-instance flips.
 */
export function effectiveSide(autoSide: Side, ov: EngravingOverride | undefined, ordinal: number): Side {
  const base = ov?.flipSide ? opposite(autoSide) : autoSide;
  return ov?.flipInstances.includes(ordinal) ? opposite(base) : base;
}

/** Parse "0-3,7,10-12" / [0,2] / 4 into a sorted, de-duplicated list of ints. */
export function parseIndexRanges(spec: unknown): number[] {
  const out = new Set<number>();
  const add = (token: string) => {
    const t = token.trim();
    if (!t) return;
    const m = t.match(/^(\d+)\s*-\s*(\d+)$/);
    if (m) {
      const lo = Number(m[1]);
      const hi = Number(m[2]);
      for (let i = lo; i <= hi; i += 1) out.add(i);
    } else if (/^\d+$/.test(t)) {
      out.add(Number(t));
    }
  };
  if (typeof spec === "number") out.add(spec);
  else if (Array.isArray(spec)) spec.forEach((s) => add(String(s)));
  else if (typeof spec === "string") spec.split(",").forEach(add);
  return [...out].sort((a, b) => a - b);
}

/** Serialize ordinals back to a compact "0,2,4-6" string. */
function formatIndexRanges(ids: number[]): string {
  const sorted = [...new Set(ids)].sort((a, b) => a - b);
  const parts: string[] = [];
  let i = 0;
  while (i < sorted.length) {
    let j = i;
    while (j + 1 < sorted.length && sorted[j + 1] === sorted[j] + 1) j += 1;
    parts.push(i === j ? `${sorted[i]}` : `${sorted[i]}-${sorted[j]}`);
    i = j + 1;
  }
  return parts.join(",");
}

/** Parse the whole `engraving_overrides` map into editable override objects. */
export function parseEngravingOverrides(text: string | null): Record<string, EngravingOverride> {
  const out: Record<string, EngravingOverride> = {};
  if (!text) return out;
  let data: unknown;
  try {
    data = parse(text);
  } catch {
    return out;
  }
  const eo = (data as { engraving_overrides?: Record<string, unknown> } | null)?.engraving_overrides;
  if (!eo || typeof eo !== "object") return out;
  for (const [key, raw] of Object.entries(eo)) {
    const o = (raw ?? {}) as Record<string, unknown>;
    out[key] = {
      flipHorizontal: !!o.flip_horizontal,
      flipVertical: !!o.flip_vertical,
      flipSide: !!o.flip_side,
      flipInstances: parseIndexRanges(o.flip_side_instances),
    };
  }
  return out;
}

/**
 * Return new `project.yaml` text with `partKey`'s engraving override applied.
 * Keys are removed when they hold their default (false / empty) so the file
 * stays clean; an emptied part node (and an emptied section) is pruned too.
 *
 * Returns null if there is no base text to edit (so callers don't create a
 * `project.yaml` that lacks imports/sheets/etc).
 */
export function applyEngravingOverride(
  text: string | null,
  partKey: string,
  ov: EngravingOverride,
): string | null {
  if (text == null) return null;
  const doc = parseDocument(text);

  const setOrDelete = (key: string, value: boolean | string) => {
    const path = ["engraving_overrides", partKey, key];
    if (value === false || value === "") {
      // deleteIn throws if an intermediate node (e.g. a not-yet-created part)
      // is missing, so guard with hasIn.
      if (doc.hasIn(path)) doc.deleteIn(path);
    } else {
      doc.setIn(path, value);
    }
  };

  setOrDelete("flip_horizontal", ov.flipHorizontal);
  setOrDelete("flip_vertical", ov.flipVertical);
  setOrDelete("flip_side", ov.flipSide);
  setOrDelete("flip_side_instances", ov.flipInstances.length ? formatIndexRanges(ov.flipInstances) : "");

  // Prune an emptied part node, then an emptied section.
  const partNode = doc.getIn(["engraving_overrides", partKey]) as { items?: unknown[] } | undefined;
  if (partNode && Array.isArray(partNode.items) && partNode.items.length === 0) {
    doc.deleteIn(["engraving_overrides", partKey]);
  }
  const section = doc.getIn(["engraving_overrides"]) as { items?: unknown[] } | undefined;
  if (section && Array.isArray(section.items) && section.items.length === 0) {
    doc.deleteIn(["engraving_overrides"]);
  }

  return String(doc);
}
