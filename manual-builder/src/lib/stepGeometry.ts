/**
 * Resolves what a step looks like in 3D: which instances are already built vs.
 * newly added, and the world matrix for each (added parts carry the explode
 * offset). All lookups gracefully skip instance ids that no longer exist in the
 * model, so a manual stays usable after the source CAD changes.
 */

import { type ManualDocument, partExplode, resolveExisting } from "../types/manual";
import type { Mat4, ModelData, ModelInstance, Vec3 } from "../types/model";
import {
  inverseTransformDirection,
  normalize,
  scale,
  transformDirection,
  translateMatrix,
} from "./vec";

export type InstanceRole = "completed" | "added" | "neutral";

export interface ResolvedInstance {
  instance: ModelInstance;
  /** World transform including any explode offset. */
  matrix: Mat4;
  role: InstanceRole;
  /** True when this instance has an active explode offset. */
  exploded: boolean;
}

export function explodeOffset(distanceMm: number, direction: Vec3): Vec3 {
  return scale(normalize(direction), distanceMm);
}

/**
 * Resolve all instances visible in the step at `stepIndex`.
 *
 * `includeRepeatCopies` controls whether a repeated step's extra copies are
 * emitted. The authoring/manual view shows only the primary (the single
 * instance the printed manual depicts); the combined multi-copy render is a
 * preview opt-in.
 */
export function resolveStepInstances(
  model: ModelData,
  doc: ManualDocument,
  stepIndex: number,
  explodeScale = 1,
  includeRepeatCopies = true,
): ResolvedInstance[] {
  const byId = new Map(model.instances.map((i) => [i.id, i]));
  const step = doc.steps[stepIndex];
  if (!step) return resolveAllInPlace(model);

  const resolved: ResolvedInstance[] = [];

  // Context parts derived from this step's dependencies.
  // They can carry explode overrides just like added parts.
  const addedSet = new Set(step.added);
  for (const id of resolveExisting(doc, step)) {
    if (addedSet.has(id)) continue; // a part added this step takes precedence
    const instance = byId.get(id);
    if (!instance) continue;
    const explode = partExplode(step, id);
    const matrix = explode
      ? translateMatrix(instance.matrix, explodeOffset(explode.distance_mm * explodeScale, explode.direction))
      : instance.matrix;
    resolved.push({ instance, matrix, role: "completed", exploded: !!explode });
  }
  // New parts (the primary/template copy): offset only if they carry explode.
  for (const id of step.added) {
    const instance = byId.get(id);
    if (!instance) continue;
    const explode = partExplode(step, id);
    const matrix = explode
      ? translateMatrix(instance.matrix, explodeOffset(explode.distance_mm * explodeScale, explode.direction))
      : instance.matrix;
    resolved.push({ instance, matrix, role: "added", exploded: !!explode });
  }

  // Repeat copies (preview only): render each copy's instances, mirroring the
  // template part's explode. The explode direction is re-expressed through the
  // copy's placement (template-world → template-local → copy-world) so copies
  // explode along their own orientation rather than all sharing one world
  // direction. Skipped in the authoring view, where only the primary is shown.
  for (const copy of includeRepeatCopies ? step.repeat?.copies ?? [] : []) {
    for (const [templateId, copyId] of Object.entries(copy.map)) {
      const instance = byId.get(copyId);
      const templateInst = byId.get(templateId);
      if (!instance || !templateInst) continue;
      const explode = partExplode(step, templateId);
      let matrix = instance.matrix;
      if (explode) {
        const localDir = inverseTransformDirection(templateInst.matrix, explode.direction);
        const copyDir = transformDirection(instance.matrix, localDir);
        matrix = translateMatrix(
          instance.matrix,
          explodeOffset(explode.distance_mm * explodeScale, copyDir),
        );
      }
      resolved.push({ instance, matrix, role: "added", exploded: !!explode });
    }
  }
  return resolved;
}

/** Fallback when no step is selected: show the whole assembly in place. */
export function resolveAllInPlace(model: ModelData): ResolvedInstance[] {
  return model.instances.map((instance) => ({
    instance,
    matrix: instance.matrix,
    role: "neutral" as const,
    exploded: false,
  }));
}

export function resolvedById(resolved: ResolvedInstance[]): Map<string, ResolvedInstance> {
  return new Map(resolved.map((r) => [r.instance.id, r]));
}
