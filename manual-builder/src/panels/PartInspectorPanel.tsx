import { useMemo } from "react";

import { Field, NumberInput, Section, Toggle, Vec3Input } from "../components/fields";
import { partColor } from "../lib/color";
import { smartExplodeDirection } from "../lib/geometry";
import { effectiveSide, emptyOverride } from "../lib/projectConfig";
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
  type ManualDocument,
  type Step,
} from "../types/manual";
import type { ModelData, ModelInstance, ModelPart } from "../types/model";

const ordinalOf = (instanceId: string) => Number(instanceId.slice(instanceId.lastIndexOf("#") + 1));

/** Edits the selected part: engraving overrides (project.yaml) and per-step explode. */
export function PartInspectorPanel() {
  const manual = useAppStore((s) => s.manual);
  const model = useAppStore((s) => s.model);
  const step = useAppStore(selectedStep);
  const selectedInstanceId = useAppStore((s) => s.selectedInstanceId);
  const selectedInstanceIds = useAppStore((s) => s.selectedInstanceIds);
  const engravingOverrides = useAppStore((s) => s.engravingOverrides);
  const configSaveState = useAppStore((s) => s.configSaveState);
  const projectConfigText = useAppStore((s) => s.projectConfigText);

  const setPartsExplode = useAppStore((s) => s.setPartsExplode);
  const setEngravingOverride = useAppStore((s) => s.setEngravingOverride);
  const setEngravingInstanceFlips = useAppStore((s) => s.setEngravingInstanceFlips);
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

  if (!manual) return <div className="panel-empty">No manual loaded.</div>;

  const instance = selectedInstanceId ? instById.get(selectedInstanceId) : null;
  if (!instance) {
    return <div className="panel-empty">Click a part in the viewport or Parts list to edit it.</div>;
  }

  const id = instance.id;
  const partKey = instance.partKey;
  const partMeta = partByKey.get(partKey);
  const engraving = partMeta?.engraving ?? null;

  // --- Engraving overrides (project.yaml) ---
  const ov = engravingOverrides[partKey] ?? emptyOverride();
  // The instances of this part that are part of the current selection (so the
  // per-instance flip can act on all of them at once); default to the anchor.
  const selOrdinals = (() => {
    const ofPart = selectedInstanceIds.filter((iid) => instById.get(iid)?.partKey === partKey);
    return (ofPart.length ? ofPart : [id]).map(ordinalOf);
  })();
  const allSelFlipped = selOrdinals.length > 0 && selOrdinals.every((o) => ov.flipInstances.includes(o));
  const anchorSide = engraving ? effectiveSide(engraving.autoSide, ov, ordinalOf(id)) : null;

  const configStatus =
    projectConfigText == null
      ? "No project.yaml found — changes can't be saved."
      : configSaveState === "saving"
        ? "Saving to project.yaml…"
        : configSaveState === "saved"
          ? "Saved to project.yaml."
          : configSaveState === "error"
            ? "Failed to save project.yaml."
            : null;

  // --- Explode (per-step) ---
  const isVisible = (iid: string) =>
    !!(step && (allAddedInstanceIds(step).includes(iid) || existing.has(iid)));

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
            <div className="part-head-sub">{partKey}</div>
          </div>
        </div>
        <div className="part-actions">
          <button className="btn btn--small btn--ghost" onClick={() => selectInstance(null)}>
            Deselect
          </button>
        </div>
      </Section>

      <Section title="Explode">
        {!step ? (
          <div className="hint">Select a step to position this part.</div>
        ) : !isVisible(id) ? (
          <div className="hint">This part is not visible in the current step.</div>
        ) : (
          <ExplodeControls
            step={step}
            manual={manual}
            model={model}
            instance={instance}
            partMeta={partMeta}
            selectedInstanceIds={selectedInstanceIds}
            instById={instById}
            setPartsExplode={setPartsExplode}
          />
        )}
      </Section>

      {engraving ? (
        <Section title="Engraving">
          <div className="subhead">
            Side
            <span className="badge">{anchorSide}</span>
          </div>
          <Toggle
            label="Flip side (whole part)"
            checked={ov.flipSide}
            onChange={(b) => setEngravingOverride(partKey, { flipSide: b })}
          />
          {(partMeta?.count ?? 1) > 1 ? (
            <>
              <Toggle
                label={
                  selOrdinals.length > 1
                    ? `Flip ${selOrdinals.length} selected instances`
                    : "Flip this instance"
                }
                checked={allSelFlipped}
                onChange={(b) => setEngravingInstanceFlips(partKey, selOrdinals, b)}
              />
              <div className="hint">
                {ov.flipInstances.length} of {partMeta?.count} instances individually flipped.
              </div>
            </>
          ) : null}

          <div className="subhead">Overlay alignment</div>
          <Toggle
            label="Flip horizontal"
            checked={ov.flipHorizontal}
            onChange={(b) => setEngravingOverride(partKey, { flipHorizontal: b })}
          />
          <Toggle
            label="Flip vertical"
            checked={ov.flipVertical}
            onChange={(b) => setEngravingOverride(partKey, { flipVertical: b })}
          />
          <div className="hint">
            Horizontal/vertical flips preview approximately; exact alignment is applied on the
            next <code>./process</code>.
          </div>
          {configStatus ? <div className="hint">{configStatus}</div> : null}
        </Section>
      ) : null}
    </div>
  );
}

/** Per-step explode editing for the focused part (and any other selected parts). */
function ExplodeControls({
  step,
  manual,
  model,
  instance,
  partMeta,
  selectedInstanceIds,
  instById,
  setPartsExplode,
}: {
  step: Step;
  manual: ManualDocument;
  model: ModelData | null;
  instance: ModelInstance;
  partMeta: ModelPart | undefined;
  selectedInstanceIds: string[];
  instById: Map<string, ModelInstance>;
  setPartsExplode: (ids: string[], explode: ExplodeSettings | null) => void;
}) {
  const id = instance.id;
  // Explode is authored on the template; if a repeat copy is selected, edit its
  // template so the change mirrors to every copy.
  const templateId = templateInstanceFor(step, id) ?? id;
  const multi = selectedInstanceIds.length > 1;
  const explodeTargets = multi ? selectedInstanceIds : [templateId];
  const applyExplode = (e: ExplodeSettings | null) => setPartsExplode(explodeTargets, e);

  const explode = partExplode(step, templateId);
  const group = subassemblyGroup(manual, step, templateId);
  const groupSize = group.length;
  const repeated = isRepeated(step);
  const templateInstance = instById.get(templateId) ?? instance;

  const defaultExplode = (): ExplodeSettings => ({
    distance_mm: 30,
    direction:
      partMeta?.bbox != null
        ? smartExplodeDirection(templateInstance.matrix, partMeta.bbox, model?.bounds ?? null)
        : upVector(manual.defaults.upAxis),
  });

  return (
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
  );
}
