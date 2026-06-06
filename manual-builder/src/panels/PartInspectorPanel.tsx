import { useMemo } from "react";

import { Field, NumberInput, Section, Toggle, Vec3Input } from "../components/fields";
import { partColor } from "../lib/color";
import { smartExplodeDirection } from "../lib/geometry";
import { upVector } from "../lib/vec";
import { selectedStep, useAppStore } from "../store/useAppStore";
import {
  allAddedInstanceIds,
  isRepeated,
  partExplode,
  repeatCount,
  resolveExisting,
  subassemblyGroup,
  templateInstanceFor,
  type ExplodeSettings,
} from "../types/manual";
import type { ModelInstance, ModelPart } from "../types/model";

/** Edits the part selected within the current step: membership and explode. */
export function PartInspectorPanel() {
  const manual = useAppStore((s) => s.manual);
  const model = useAppStore((s) => s.model);
  const step = useAppStore(selectedStep);
  const selectedInstanceId = useAppStore((s) => s.selectedInstanceId);
  const selectedInstanceIds = useAppStore((s) => s.selectedInstanceIds);

  const setPartsExplode = useAppStore((s) => s.setPartsExplode);
  const selectInstance = useAppStore((s) => s.selectInstance);

  const instById = useMemo(() => {
    const map = new Map<string, ModelInstance>();
    for (const inst of model?.instances ?? []) map.set(inst.id, inst);
    return map;
  }, [model]);
  const partByKey = useMemo(() => {
    const map = new Map<string, ModelPart>();
    for (const part of model?.parts ?? []) map.set(part.key, part);
    return map;
  }, [model]);
  const existing = useMemo(
    () => (manual && step ? resolveExisting(manual, step) : new Set<string>()),
    [manual, step],
  );

  const isVisible = (iid: string) =>
    !!(step && (allAddedInstanceIds(step).includes(iid) || existing.has(iid)));

  if (!manual) return <div className="panel-empty">No manual loaded.</div>;
  if (!step) return <div className="panel-empty">Select a step first.</div>;

  const instance = selectedInstanceId ? instById.get(selectedInstanceId) : null;
  if (!instance) {
    return <div className="panel-empty">Click a part in the viewport or Parts list to edit it.</div>;
  }

  const id = instance.id;
  // Explode is authored on the template; if a repeat copy is selected, edit its
  // template part so the change mirrors to every copy.
  const templateId = templateInstanceFor(step, id) ?? id;

  // When several parts are selected, explode edits apply to all of them with the
  // same settings. Otherwise just the focused part (its subassembly).
  const multi = selectedInstanceIds.length > 1;
  const explodeTargets = multi ? selectedInstanceIds : [templateId];
  const applyExplode = (e: ExplodeSettings | null) => setPartsExplode(explodeTargets, e);
  const explode = partExplode(step, templateId);
  const group = subassemblyGroup(manual, step, templateId);
  const groupSize = group.length;
  const partMeta = partByKey.get(instance.partKey);
  const repeated = isRepeated(step);
  // Explode direction is stored in the template's frame, then re-expressed per
  // copy at render time — so compute defaults from the template instance.
  const templateInstance = instById.get(templateId) ?? instance;

  // A sensible starting offset when enabling explode for a part.
  const defaultExplode = (): ExplodeSettings => {
    const direction =
      partMeta?.bbox != null
        ? smartExplodeDirection(templateInstance.matrix, partMeta.bbox, model?.bounds ?? null)
        : upVector(manual.defaults.upAxis);
    return {
      distance_mm: 30,
      direction,
    };
  };

  return (
    <div className="panel panel--inspector">
      <Section title="Part">
        <div className="part-head">
          <span
            className="swatch"
            style={{ background: partMeta ? partColor(partMeta.color) : "#ccc" }}
          />
          <div>
            <div className="part-head-title">{instance.sheet ?? id}</div>
            <div className="part-head-sub">{instance.partKey}</div>
          </div>
        </div>

        {!isVisible(id) ? (
          <div className="hint">This part is not visible in the current step.</div>
        ) : (
          <>
            <div className="subhead">
              Explode
              <Toggle
                label={
                  multi
                    ? `${selectedInstanceIds.length} selected parts`
                    : groupSize > 1
                      ? `subassembly (${groupSize} parts)`
                      : "this part"
                }
                checked={explode !== null}
                onChange={(b) => applyExplode(b ? defaultExplode() : null)}
              />
            </div>
            {multi ? (
              <div className="hint">
                Applies the same explode to all {selectedInstanceIds.length} selected parts.
              </div>
            ) : repeated ? (
              <div className="hint">Mirrors to all {repeatCount(step)} copies of this subassembly.</div>
            ) : null}
            {explode ? (
              <>
                <Field label="Distance (mm)">
                  <NumberInput
                    value={explode.distance_mm}
                    onChange={(n) => applyExplode({ ...explode, distance_mm: n })}
                  />
                </Field>
                <Field label="Direction">
                  <Vec3Input
                    value={explode.direction}
                    onChange={(v) => applyExplode({ ...explode, direction: v })}
                  />
                </Field>
              </>
            ) : (
              <div className="hint">Stays in place. Toggle explode to offset it.</div>
            )}
          </>
        )}

        <div className="part-actions">
          <button className="btn btn--small btn--ghost" onClick={() => selectInstance(null)}>
            Deselect
          </button>
        </div>
      </Section>
    </div>
  );
}
