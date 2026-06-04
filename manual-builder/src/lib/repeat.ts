/**
 * Auto-detection of repeated subassemblies.
 *
 * Given a *template* set of instances (the parts authored as "new" in a step),
 * find the other physical copies of that same subassembly elsewhere in the
 * model. Each copy is returned as a correspondence map template→copy so that
 * authored instructions (explode, connections) can mirror onto it.
 *
 * Approach (rotation- and translation-tolerant, no full rigid fit):
 *  - Anchor on the template's rarest part (most discriminating).
 *  - Characterize the template by each part's distance to the anchor — a
 *    signature invariant to where/how the copy is placed.
 *  - For every other anchor-part instance in the model, try to fill the whole
 *    template by matching each part to the nearest unused instance of the same
 *    partKey whose distance-to-anchor matches the template, and which sits
 *    within the subassembly's own footprint. Accept only fully-matched copies.
 *
 * Symmetric ambiguities (two same-key parts equidistant from the anchor) may
 * pair imperfectly, but always onto a correct-partKey part, so mirrored
 * instructions still land sensibly. A full Kabsch alignment is a future upgrade.
 */

import type { ModelData, ModelInstance, Vec3 } from "../types/model";
import type { RepeatCopy } from "../types/manual";

function position(inst: ModelInstance): Vec3 {
  const m = inst.matrix;
  return [m[12], m[13], m[14]];
}

function dist(a: Vec3, b: Vec3): number {
  return Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
}

interface TemplatePart {
  id: string;
  partKey: string;
  /** Distance from this part to the anchor part. */
  toAnchor: number;
}

/**
 * Detect repeated copies of the subassembly described by `templateIds`.
 * `exclude` lists instance ids already consumed by other steps; they are never
 * matched into a copy. Returns the additional copies (never the template).
 */
export function detectRepeats(
  model: ModelData,
  templateIds: string[],
  exclude: Set<string> = new Set(),
): RepeatCopy[] {
  const byId = new Map(model.instances.map((i) => [i.id, i]));
  const template = templateIds.map((id) => byId.get(id)).filter((x): x is ModelInstance => !!x);
  if (template.length === 0) return [];

  // Global part-key frequencies → pick the rarest template key as the anchor.
  const globalCount = new Map<string, number>();
  for (const inst of model.instances) {
    globalCount.set(inst.partKey, (globalCount.get(inst.partKey) ?? 0) + 1);
  }
  const anchorTemplate = template.reduce((best, t) =>
    (globalCount.get(t.partKey) ?? 0) < (globalCount.get(best.partKey) ?? 0) ? t : best,
  );
  const anchorPos = position(anchorTemplate);

  // Template signature: each part's distance to the anchor, and the footprint.
  const parts: TemplatePart[] = template.map((t) => ({
    id: t.id,
    partKey: t.partKey,
    toAnchor: dist(position(t), anchorPos),
  }));
  let diameter = 0;
  for (const a of template) {
    for (const b of template) diameter = Math.max(diameter, dist(position(a), position(b)));
  }
  // Distance-match tolerance and a compactness gate (copy must be template-sized).
  const tol = Math.max(diameter * 0.1, 1.0);
  const footprint = diameter * 1.5 + tol;

  // Instances available to be matched, grouped by partKey.
  const used = new Set<string>([...templateIds, ...exclude]);
  const poolByKey = new Map<string, ModelInstance[]>();
  for (const inst of model.instances) {
    if (used.has(inst.id)) continue;
    (poolByKey.get(inst.partKey) ?? poolByKey.set(inst.partKey, []).get(inst.partKey)!).push(inst);
  }

  // Try each unused anchor-key instance as a candidate copy anchor.
  const anchorCandidates = (poolByKey.get(anchorTemplate.partKey) ?? [])
    .slice()
    .sort((a, b) => cmpPos(position(a), position(b)));

  const copies: RepeatCopy[] = [];
  for (const ca of anchorCandidates) {
    if (used.has(ca.id)) continue;
    const caPos = position(ca);
    const localUsed = new Set<string>();
    const map: Record<string, string> = {};
    let ok = true;

    for (const part of parts) {
      if (part.id === anchorTemplate.id) {
        map[part.id] = ca.id;
        localUsed.add(ca.id);
        continue;
      }
      const candidates = poolByKey.get(part.partKey) ?? [];
      let best: ModelInstance | null = null;
      let bestErr = Infinity;
      for (const c of candidates) {
        if (used.has(c.id) || localUsed.has(c.id)) continue;
        const cPos = position(c);
        if (dist(cPos, caPos) > footprint) continue; // not within this copy's footprint
        const err = Math.abs(dist(cPos, caPos) - part.toAnchor);
        if (err < bestErr || (err === bestErr && best && cmpPos(cPos, position(best)) < 0)) {
          bestErr = err;
          best = c;
        }
      }
      if (!best || bestErr > tol) { ok = false; break; }
      map[part.id] = best.id;
      localUsed.add(best.id);
    }

    if (!ok) continue;
    copies.push({ id: crypto.randomUUID(), map });
    for (const id of localUsed) used.add(id);
  }

  // Stable order: by each copy's anchor position.
  copies.sort((a, b) =>
    cmpPos(position(byId.get(a.map[anchorTemplate.id])!), position(byId.get(b.map[anchorTemplate.id])!)),
  );
  return copies;
}

function cmpPos(a: Vec3, b: Vec3): number {
  return a[0] - b[0] || a[1] - b[1] || a[2] - b[2];
}
