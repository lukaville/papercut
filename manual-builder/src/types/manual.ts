/**
 * Types and helpers for the hand-authored manual document, persisted to
 * `[project]/manual/manual.json`.
 *
 * Design notes (robustness to CAD changes):
 *  - Parts/instances are referenced by their stable model id (`partKey#ordinal`),
 *    never by sheet labels.
 *  - Vertices are referenced by index into the part's topological vertex list.
 *  - Step context is dependency-based: a step's "existing" (already-built) parts
 *    are derived from the steps it `dependsOn` (transitively). By default a step
 *    depends on the previous one, but a step can be independent (no deps, starts
 *    from scratch) or depend on several steps (subassemblies coming together).
 *    Dependencies are by step id, so reordering never silently changes context.
 *  - Explode is per-part and on-demand: a part is only offset if it carries its
 *    own explode override; there is no step- or document-level default explode.
 */

import type { Vec3 } from "./model";

export interface ViewSettings {
  /** Rotation around the up axis, degrees. */
  azimuthDeg: number;
  /** Tilt above the horizontal plane, degrees. */
  elevationDeg: number;
  /** Orthographic zoom multiplier (1 = fit to model). */
  zoom: number;
}

export interface ExplodeSettings {
  /** Offset distance applied to the part, in mm. */
  distance_mm: number;
  /** World-space direction the part is pushed along. */
  direction: Vec3;
}

/** A reference to one topological vertex of a placed instance. */
export interface VertexRef {
  instance: string;
  vertex: number;
}

/** A dashed leader line from a vertex on a new part to a target part. */
export interface Connection {
  id: string;
  from: VertexRef;
  /** Instance id of the target part. The "to" endpoint is the vertex on this
   *  part nearest to the assembled position of `from`. */
  toPart: string;
}

/** Per-part settings within a step, keyed by instance id. Forward-looking: a
 * place to attach more per-part overrides later (e.g. color, annotation). */
export interface StepPartSettings {
  /** On-demand explode for this part; absent/null means it stays in place. */
  explode?: ExplodeSettings | null;
}

/**
 * One physical copy of a repeated subassembly. `map` pairs each *template*
 * instance (the ids in `step.added`) with the corresponding instance in this
 * copy. The map is the single source of correspondence that lets authored
 * instructions (explode, connections) mirror from the template onto every copy.
 */
export interface RepeatCopy {
  id: string;
  /** template instanceId -> this copy's instanceId */
  map: Record<string, string>;
}

/**
 * Makes a step "repeated": the same subassembly built in several places. The
 * step's `added` is the primary copy (the template you author against); these
 * are the *additional* copies. In the final manual the whole thing reads as one
 * step ("build the leg ×N").
 */
export interface StepRepeat {
  copies: RepeatCopy[];
}

export interface Step {
  id: string;
  title: string;
  description: string;
  /** Per-step camera override; `null` inherits the document default view. */
  view: ViewSettings | null;
  /** Step ids this step builds upon. Their visible parts become this step's
   * context (existing parts), resolved transitively. Empty = independent. */
  dependsOn: string[];
  /** Parts introduced in this step — highlighted, optionally exploded. This is
   * the primary copy when the step is repeated. */
  added: string[];
  /** Per-part settings (currently explode), keyed by *template* instance id. */
  parts?: Record<string, StepPartSettings>;
  /** Optional: turns this into a repeated subassembly step. */
  repeat?: StepRepeat | null;
  connections: Connection[];
}

export type UpAxis = "x" | "y" | "z";

export interface ManualDefaults {
  upAxis: UpAxis;
  view: ViewSettings;
}

export interface ManualDocument {
  schemaVersion: number;
  title: string;
  defaults: ManualDefaults;
  steps: Step[];
}

export const MANUAL_SCHEMA_VERSION = 1;

const DEFAULT_VIEW: ViewSettings = { azimuthDeg: 45, elevationDeg: 35.264, zoom: 1 };

/**
 * The canonical empty manual, used when a project has no `manual.json` yet so
 * the editor can start authoring immediately.
 */
export function defaultManual(): ManualDocument {
  return {
    schemaVersion: MANUAL_SCHEMA_VERSION,
    title: "Assembly Manual",
    // CAD is Z-up; the isometric camera orbits around this axis.
    defaults: { upAxis: "z", view: { ...DEFAULT_VIEW } },
    steps: [],
  };
}

// --- Derived helpers ---------------------------------------------------------

export function effectiveView(step: Step, defaults: ManualDefaults): ViewSettings {
  return step.view ?? defaults.view;
}

/** This part's on-demand explode, or null if it stays in place. */
export function partExplode(step: Step, instanceId: string): ExplodeSettings | null {
  return step.parts?.[instanceId]?.explode ?? null;
}

export function hasPartExplode(step: Step, instanceId: string): boolean {
  return step.parts?.[instanceId]?.explode != null;
}

// --- Repeated subassemblies --------------------------------------------------

export function isRepeated(step: Step): boolean {
  return !!step.repeat && step.repeat.copies.length > 0;
}

/** Total physical copies the step represents (primary + extra copies). */
export function repeatCount(step: Step): number {
  return 1 + (step.repeat?.copies.length ?? 0);
}

/** Every instance id introduced by the extra copies (excludes the primary). */
export function repeatCopyInstanceIds(step: Step): string[] {
  if (!step.repeat) return [];
  const ids: string[] = [];
  for (const copy of step.repeat.copies) ids.push(...Object.values(copy.map));
  return ids;
}

/**
 * All instance ids this step makes visible as "new": the primary `added` plus
 * every repeat copy's instances. This is the set later steps inherit as context.
 */
export function allAddedInstanceIds(step: Step): string[] {
  return [...step.added, ...repeatCopyInstanceIds(step)];
}

/**
 * Map any instance belonging to this step back to its *template* (primary)
 * instance. Template parts map to themselves; copy parts map to the template
 * id they correspond to; anything else returns null. Authoring (explode,
 * connections) is keyed by the template id so it mirrors to all copies.
 */
export function templateInstanceFor(step: Step, instanceId: string): string | null {
  if (step.added.includes(instanceId)) return instanceId;
  for (const copy of step.repeat?.copies ?? []) {
    for (const [templateId, copyId] of Object.entries(copy.map)) {
      if (copyId === instanceId) return templateId;
    }
  }
  return null;
}

export type PartRole = "new" | "existing" | "none";

/**
 * Resolve the set of instance ids that count as already-built "existing"
 * context for a step: the union of every dependency step's visible parts
 * (its own added parts plus its transitively-resolved existing), with a
 * cycle guard so malformed dependency graphs can't loop.
 */
export function resolveExisting(doc: ManualDocument, step: Step): Set<string> {
  const byId = new Map(doc.steps.map((s) => [s.id, s]));
  const out = new Set<string>();
  const seen = new Set<string>();
  const visit = (current: Step) => {
    for (const depId of current.dependsOn) {
      if (seen.has(depId)) continue;
      seen.add(depId);
      const dep = byId.get(depId);
      if (!dep) continue;
      visit(dep);
      // A repeated dependency contributes all of its copies as built context.
      for (const id of allAddedInstanceIds(dep)) out.add(id);
    }
  };
  visit(step);
  return out;
}

export function partRoleIn(
  step: Step,
  existing: Set<string>,
  instanceId: string,
): PartRole {
  if (step.added.includes(instanceId)) return "new";
  if (existing.has(instanceId)) return "existing";
  return "none";
}

/**
 * Returns all instance IDs visible in `step` that belong to the same source
 * subassembly copy as `instanceId`. Visibility includes both parts inherited
 * from dependencies (resolveExisting) and parts in step.added. "Source" is
 * the (step, copy) pair that first introduced the part — each physical copy of
 * a repeated dependency is its own independent group, so they can be exploded
 * separately. Parts added fresh in this step form singleton groups.
 */
export function subassemblyGroup(
  doc: ManualDocument,
  step: Step,
  instanceId: string,
): string[] {
  const stepById = new Map(doc.steps.map((s) => [s.id, s]));
  // Track (stepId, copyKey) so each repeat copy is its own independent group.
  // copyKey "primary" = the dep step's own added parts; copy.id = a specific copy.
  type Source = { stepId: string; copyKey: string };
  const sourceOf = new Map<string, Source>();
  const visited = new Set<string>();

  const traverse = (sId: string) => {
    if (visited.has(sId)) return;
    visited.add(sId);
    const s = stepById.get(sId);
    if (!s) return;
    for (const depId of s.dependsOn) traverse(depId);
    for (const id of s.added) {
      if (!sourceOf.has(id)) sourceOf.set(id, { stepId: sId, copyKey: "primary" });
    }
    for (const copy of s.repeat?.copies ?? []) {
      for (const copyId of Object.values(copy.map)) {
        if (!sourceOf.has(copyId)) sourceOf.set(copyId, { stepId: sId, copyKey: copy.id });
      }
    }
  };
  for (const depId of step.dependsOn) traverse(depId);

  const source = sourceOf.get(instanceId);
  if (!source) return [instanceId]; // added fresh in this step — no group

  // Group spans all visible instances: existing (from deps) + explicitly added.
  const allVisible = new Set([...resolveExisting(doc, step), ...step.added]);
  return [...allVisible].filter((id) => {
    const so = sourceOf.get(id);
    return so?.stepId === source.stepId && so?.copyKey === source.copyKey;
  });
}

/** Would adding `depId` as a dependency of `stepId` create a cycle? */
export function wouldCreateCycle(doc: ManualDocument, stepId: string, depId: string): boolean {
  if (stepId === depId) return true;
  const byId = new Map(doc.steps.map((s) => [s.id, s]));
  const seen = new Set<string>();
  const reaches = (fromId: string): boolean => {
    if (fromId === stepId) return true;
    if (seen.has(fromId)) return false;
    seen.add(fromId);
    const from = byId.get(fromId);
    if (!from) return false;
    return from.dependsOn.some(reaches);
  };
  return reaches(depId);
}

// --- Migration ---------------------------------------------------------------

/**
 * Normalize a loaded document to the current schema. Tolerates partial/legacy
 * data. Legacy manuals (which had implicit dependencies — every step built on
 * all earlier ones) are migrated to an explicit chain (`dependsOn` = previous
 * step), which reproduces the same visible context.
 */
export function normalizeManual(raw: unknown): ManualDocument {
  const doc = (raw ?? {}) as Partial<ManualDocument> & { steps?: unknown[] };
  const defaults: ManualDefaults = {
    upAxis: (doc.defaults?.upAxis as UpAxis) ?? "z",
    view: doc.defaults?.view ?? { ...DEFAULT_VIEW },
  };

  const rawSteps: unknown[] = Array.isArray(doc.steps) ? doc.steps : [];
  const steps: Step[] = [];
  let prevId: string | null = null;

  for (const entry of rawSteps) {
    const s = (entry ?? {}) as Record<string, unknown>;
    const id = (s.id as string) ?? crypto.randomUUID();
    const added: string[] = Array.isArray(s.added) ? (s.added as string[]) : [];
    const dependsOn = Array.isArray(s.dependsOn)
      ? (s.dependsOn as string[]).filter((x) => typeof x === "string")
      : prevId
        ? [prevId] // legacy: implicit chain to the previous step
        : [];

    steps.push({
      id,
      title: (s.title as string) ?? "",
      description: (s.description as string) ?? "",
      view: (s.view as ViewSettings | null) ?? null,
      dependsOn,
      added,
      parts: (s.parts as Record<string, StepPartSettings>) ?? undefined,
      repeat: normalizeRepeat(s.repeat),
      connections: Array.isArray(s.connections)
        ? (s.connections as Record<string, unknown>[])
            .filter((c) => c && typeof c.id === "string" && c.from)
            .map((c) => ({
              id: c.id as string,
              from: c.from as VertexRef,
              // legacy: old format stored 'to: VertexRef' — migrate to toPart
              toPart: (c.toPart as string | undefined) ??
                ((c.to as { instance?: string } | undefined)?.instance ?? ""),
            }))
            .filter((c) => c.toPart !== "")
        : [],
    });
    prevId = id;
  }

  return {
    schemaVersion: MANUAL_SCHEMA_VERSION,
    title: doc.title ?? "Assembly Manual",
    defaults,
    steps,
  };
}

/** Tolerantly normalize a step's optional `repeat` block. */
function normalizeRepeat(raw: unknown): StepRepeat | null {
  const r = raw as Partial<StepRepeat> | null | undefined;
  if (!r || !Array.isArray(r.copies)) return null;
  const copies: RepeatCopy[] = [];
  for (const entry of r.copies) {
    const c = (entry ?? {}) as Partial<RepeatCopy>;
    const map = c.map && typeof c.map === "object" ? (c.map as Record<string, string>) : {};
    if (Object.keys(map).length === 0) continue;
    copies.push({ id: (c.id as string) ?? crypto.randomUUID(), map });
  }
  return copies.length > 0 ? { copies } : null;
}
