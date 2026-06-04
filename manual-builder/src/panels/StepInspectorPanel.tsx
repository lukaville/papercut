import { useMemo } from "react";

import { Field, NumberInput, Section, Toggle } from "../components/fields";
import { autoConnectVertices, bboxCenter } from "../lib/geometry";
import { resolveStepInstances } from "../lib/stepGeometry";
import { applyMatrix, inverseTransformDirection } from "../lib/vec";
import { selectedStep, selectedStepIndex, useAppStore } from "../store/useAppStore";
import {
  effectiveView,
  isRepeated,
  partExplode,
  repeatCount,
  resolveExisting,
  wouldCreateCycle,
} from "../types/manual";
import type { ModelInstance } from "../types/model";
import { useMeshContext } from "../viewport/MeshProvider";

/** Edits the selected step: view, dependencies and connections. */
export function StepInspectorPanel() {
  const manual = useAppStore((s) => s.manual);
  const model = useAppStore((s) => s.model);
  const step = useAppStore(selectedStep);
  const stepIndex = useAppStore(selectedStepIndex);
  const selectedInstanceId = useAppStore((s) => s.selectedInstanceId);
  const ui = useAppStore((s) => s.ui);
  const updateStep = useAppStore((s) => s.updateStep);
  const setStepView = useAppStore((s) => s.setStepView);
  const toggleStepDependency = useAppStore((s) => s.toggleStepDependency);
  const removeConnection = useAppStore((s) => s.removeConnection);
  const clearConnections = useAppStore((s) => s.clearConnections);
  const addConnection = useAppStore((s) => s.addConnection);
  const setHoveredConnection = useAppStore((s) => s.setHoveredConnection);
  const setUi = useAppStore((s) => s.setUi);
  const detectStepRepeats = useAppStore((s) => s.detectStepRepeats);
  const clearStepRepeat = useAppStore((s) => s.clearStepRepeat);
  const removeRepeatCopy = useAppStore((s) => s.removeRepeatCopy);
  const { meshes } = useMeshContext();

  const partsByKey = useMemo(() => {
    const map = new Map<string, NonNullable<typeof model>["parts"][0]>();
    for (const p of model?.parts ?? []) map.set(p.key, p);
    return map;
  }, [model]);

  const instById = useMemo(() => {
    const map = new Map<string, ModelInstance>();
    for (const inst of model?.instances ?? []) map.set(inst.id, inst);
    return map;
  }, [model]);

  if (!manual) return <div className="panel-empty">No manual loaded.</div>;
  if (!step) return <div className="panel-empty">Select or add a step to edit it.</div>;

  const defaults = manual.defaults;
  const label = (id: string) => instById.get(id)?.sheet ?? id;

  const handleAutoConnect = () => {
    if (!model || !manual || !selectedInstanceId) return;
    // Author connectors against the primary only (1× scale, no repeat copies).
    const resolved = resolveStepInstances(model, manual, stepIndex, 1, false);
    const r = resolved.find((ri) => ri.instance.id === selectedInstanceId);
    if (!r?.exploded) return;
    const mesh = meshes.get(r.instance.partKey);
    const meta = partsByKey.get(r.instance.partKey);
    if (!mesh || !meta?.bbox) return;
    const explode = partExplode(step, r.instance.id);
    if (!explode) return;

    // Find the nearest completed part to use as the connection target.
    const fromCentroid = bboxCenter(meta.bbox);
    const fromWorld = fromCentroid ? applyMatrix(r.instance.matrix, fromCentroid) : null;
    let nearestPartId: string | null = null;
    if (fromWorld) {
      let nearestDist = Infinity;
      for (const ri of resolved) {
        if (ri.role !== "completed") continue;
        const cm = partsByKey.get(ri.instance.partKey);
        const cc = cm?.bbox ? bboxCenter(cm.bbox) : null;
        if (!cc) continue;
        const cw = applyMatrix(ri.matrix, cc);
        const d =
          (cw[0] - fromWorld[0]) ** 2 +
          (cw[1] - fromWorld[1]) ** 2 +
          (cw[2] - fromWorld[2]) ** 2;
        if (d < nearestDist) { nearestDist = d; nearestPartId = ri.instance.id; }
      }
    }
    if (!nearestPartId) return;

    const localDir = inverseTransformDirection(r.instance.matrix, explode.direction);
    const indices = autoConnectVertices(mesh.mesh.vertices, meta.bbox, localDir);
    for (const vi of indices) {
      addConnection({ instance: r.instance.id, vertex: vi }, nearestPartId);
    }
  };

  return (
    <div className="panel panel--inspector">
      <Section title="Step">
        <Field label="Description">
          <textarea
            className="input input--area"
            rows={3}
            placeholder="What happens in this step…"
            value={step.description}
            onChange={(e) => updateStep(step.id, { description: e.target.value })}
          />
        </Field>

        <div className="subhead">
          View
          <Toggle
            label="override"
            checked={step.view !== null}
            onChange={(b) => setStepView(b ? { ...effectiveView(step, defaults) } : null)}
          />
        </div>
        {step.view !== null ? (
          <>
            <Field label="Azimuth°">
              <NumberInput
                value={step.view.azimuthDeg}
                onChange={(n) => setStepView({ ...step.view!, azimuthDeg: n })}
              />
            </Field>
            <Field label="Elevation°">
              <NumberInput
                value={step.view.elevationDeg}
                onChange={(n) => setStepView({ ...step.view!, elevationDeg: n })}
              />
            </Field>
            <Field label="Zoom">
              <NumberInput
                value={step.view.zoom}
                step={0.05}
                min={0.05}
                onChange={(n) => setStepView({ ...step.view!, zoom: n })}
              />
            </Field>
            <div className="hint">
              Tip: orbit the freeform viewport, then "Save as step view".
            </div>
          </>
        ) : null}

        <div className="hint">Explode is set per part in the Part inspector.</div>
      </Section>

      <Section title="Depends on">
        <div className="hint">
          {resolveExisting(manual, step).size} existing parts inherited. Uncheck all for an
          independent step; check several to merge subassemblies.
        </div>
        {manual.steps.length <= 1 ? (
          <div className="hint">No other steps to depend on yet.</div>
        ) : (
          <ul className="dep-list">
            {manual.steps.map((other, i) => {
              if (other.id === step.id) return null;
              const checked = step.dependsOn.includes(other.id);
              const cyclic = !checked && wouldCreateCycle(manual, step.id, other.id);
              return (
                <li key={other.id}>
                  <label className={`toggle${cyclic ? " toggle--disabled" : ""}`}>
                    <input
                      type="checkbox"
                      checked={checked}
                      disabled={cyclic}
                      onChange={() => toggleStepDependency(other.id)}
                    />
                    <span>
                      Step {i + 1}
                      {other.description.trim() ? ` · ${other.description.trim()}` : ""}
                      {cyclic ? " (would cycle)" : ""}
                    </span>
                  </label>
                </li>
              );
            })}
          </ul>
        )}
      </Section>

      <Section title="Repeat">
        <div className="hint">
          Build the same subassembly in several places as one step. Add its parts
          as “new”, then auto-detect the other copies by matching part names and
          positions. The manual shows only the primary — author the view, explode
          and connections against it; the copies are a visual preview.
        </div>
        {!isRepeated(step) ? (
          <button
            className="btn btn--small"
            disabled={step.added.length === 0}
            onClick={detectStepRepeats}
            title="Find identical subassemblies elsewhere in the model"
          >
            ⧉ Detect repeated subassemblies
          </button>
        ) : (
          <>
            <div className="subhead" style={{ marginTop: 0 }}>
              <span>
                ×{repeatCount(step)} copies · {step.added.length} parts each
              </span>
              <button
                className="btn btn--small"
                onClick={detectStepRepeats}
                title="Re-run detection (replaces current copies)"
              >
                Re-detect
              </button>
              <button
                className="btn btn--small btn--danger"
                onClick={clearStepRepeat}
                title="Make this a single (non-repeated) step"
              >
                Clear
              </button>
            </div>
            <Toggle
              label="Preview all copies"
              checked={ui.previewRepeats}
              onChange={(b) => setUi({ previewRepeats: b })}
            />
            <div className="hint">
              {ui.previewRepeats
                ? "Showing all copies (preview). Authoring still applies to the primary."
                : "Showing the primary only — exactly as the manual will."}
            </div>
            <ul className="copy-list">
              <li className="copy-row copy-row--primary">
                <span>Primary (template)</span>
                <span className="copy-hint">shown in manual</span>
              </li>
              {step.repeat!.copies.map((copy, i) => (
                <li key={copy.id} className="copy-row">
                  <span>Copy {i + 2}</span>
                  <button
                    className="btn btn--icon btn--danger"
                    onClick={() => removeRepeatCopy(copy.id)}
                    title="Remove this copy (it becomes a non-repeated instance)"
                  >
                    ✕
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}
      </Section>

      <Section title={`Connections (${step.connections.length})`}>
        <div className="subhead" style={{ marginTop: 0 }}>
          <Toggle
            label="Connect mode"
            checked={ui.connectMode}
            onChange={(b) => setUi({ connectMode: b })}
          />
          <button
            className="btn btn--small"
            disabled={!selectedInstanceId}
            onClick={handleAutoConnect}
            title="Auto-add corner connections for the selected exploded part"
          >
            Auto-connect
          </button>
          <button
            className="btn btn--small btn--danger"
            disabled={step.connections.length === 0}
            onClick={clearConnections}
            title="Remove all connections from this step"
          >
            Clear
          </button>
        </div>
        {ui.connectMode ? (
          <div className="hint">
            Step 1: click a vertex on a new part. Step 2: click the target part.
          </div>
        ) : null}
        <ul className="conn-list">
          {step.connections.map((conn) => (
            <li
              key={conn.id}
              className="conn-row"
              onMouseEnter={() => setHoveredConnection(conn.id)}
              onMouseLeave={() => setHoveredConnection(null)}
            >
              <span>
                {label(conn.from.instance)} v{conn.from.vertex} → {label(conn.toPart)}
              </span>
              <button
                className="btn btn--icon btn--danger"
                onClick={() => removeConnection(conn.id)}
                title="Remove connection"
              >
                ✕
              </button>
            </li>
          ))}
        </ul>
      </Section>
    </div>
  );
}
