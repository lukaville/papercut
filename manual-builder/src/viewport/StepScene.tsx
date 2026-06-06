import { useCallback, useMemo } from "react";
import type * as THREE from "three";

import { bboxCenter } from "../lib/geometry";
import { resolveStepInstances, resolvedById } from "../lib/stepGeometry";
import type { Connection, ManualDocument, VertexRef } from "../types/manual";
import type { Mat4, ModelData, ModelPart } from "../types/model";
import { Connectors } from "./Connectors";
import { InstanceHighlight } from "./InstanceHighlight";
import { OriginGizmo } from "./OriginGizmo";
import { PartObject } from "./PartObject";
import type { PartGeometry } from "./useMeshes";

interface Props {
  model: ModelData;
  manual: ManualDocument;
  stepIndex: number;
  meshes: Map<string, PartGeometry>;
  modelRadius: number;
  showLabels: boolean;
  showVertices: boolean;
  showCompleted: boolean;
  showOrigin: boolean;
  connectMode: boolean;
  showEngravings: boolean;
  pendingVertex: VertexRef | null;
  selectedInstanceId: string | null;
  /** All selected instances (multi-select); falls back to the single anchor. */
  selectedInstanceIds?: string[];
  /** Instance hovered in the Parts list, shown as an x-ray highlight. */
  hoveredInstanceId?: string | null;
  explodeScale: number;
  /** Show all copies of a repeated step (preview) vs. only the primary. */
  previewRepeats: boolean;
  onPickVertex: (ref: VertexRef) => void;
  onSelectInstance: (id: string, additive: boolean) => void;
}

/** Renders the selected step: completed parts in place + new parts exploded. */
export function StepScene({
  model,
  manual,
  stepIndex,
  meshes,
  modelRadius,
  showLabels,
  showVertices,
  showCompleted,
  showOrigin,
  connectMode,
  showEngravings,
  pendingVertex,
  selectedInstanceId,
  selectedInstanceIds,
  hoveredInstanceId,
  explodeScale,
  previewRepeats,
  onPickVertex,
  onSelectInstance,
}: Props) {
  const partsByKey = useMemo(() => {
    const map = new Map<string, ModelPart>();
    for (const part of model.parts) map.set(part.key, part);
    return map;
  }, [model]);

  const resolved = useMemo(
    () => resolveStepInstances(model, manual, stepIndex, explodeScale, previewRepeats),
    [model, manual, stepIndex, explodeScale, previewRepeats],
  );
  const resolvedMap = useMemo(() => resolvedById(resolved), [resolved]);

  const instById = useMemo(() => {
    const map = new Map<string, ModelData["instances"][number]>();
    for (const inst of model.instances) map.set(inst.id, inst);
    return map;
  }, [model]);

  const selectedSet = useMemo(
    () => new Set(selectedInstanceIds ?? (selectedInstanceId ? [selectedInstanceId] : [])),
    [selectedInstanceIds, selectedInstanceId],
  );

  // Resolve an instance's geometry + world matrix for an x-ray highlight. Prefer
  // the step-resolved placement (correct explode), else fall back to the part's
  // assembly matrix so parts not present in the current step still highlight.
  const resolveHighlight = useCallback(
    (id: string): { geometry: THREE.BufferGeometry; matrix: Mat4 } | null => {
      const r = resolvedMap.get(id);
      const inst = instById.get(id);
      const matrix = r?.matrix ?? inst?.matrix;
      const partKey = r?.instance.partKey ?? inst?.partKey;
      if (!matrix || !partKey) return null;
      const geo = meshes.get(partKey)?.geometry;
      return geo ? { geometry: geo, matrix } : null;
    },
    [resolvedMap, instById, meshes],
  );

  const hovered = useMemo(
    () => (hoveredInstanceId ? resolveHighlight(hoveredInstanceId) : null),
    [hoveredInstanceId, resolveHighlight],
  );

  // X-ray highlights for the (explicit) multi-selection — shown half-visible so
  // selected parts are always locatable, even when occluded or not yet in the step.
  const selectionHighlights = useMemo(
    () =>
      (selectedInstanceIds ?? [])
        .map((id) => ({ id, hl: resolveHighlight(id) }))
        .filter((x): x is { id: string; hl: { geometry: THREE.BufferGeometry; matrix: Mat4 } } => x.hl !== null),
    [selectedInstanceIds, resolveHighlight],
  );

  const handlePickVertex = useCallback(
    (ref: VertexRef) => onPickVertex(ref),
    [onPickVertex],
  );

  const handleSize = Math.max(modelRadius * 0.012, 0.4);
  const step = manual.steps[stepIndex];

  // Connections are authored on the template; mirror them onto each repeat copy
  // by remapping endpoints through the copy's correspondence map. Endpoints that
  // fall outside the subassembly (e.g. a shared context part) are kept as-is.
  const connections = useMemo<Connection[]>(() => {
    if (!step) return [];
    const all = [...step.connections];
    // Copy connectors only exist in the multi-copy preview; the authoring view
    // shows just the primary's authored connectors.
    for (const copy of previewRepeats ? step.repeat?.copies ?? [] : []) {
      const remap = (id: string) => copy.map[id] ?? id;
      for (const conn of step.connections) {
        all.push({
          id: `${conn.id}@${copy.id}`,
          from: { instance: remap(conn.from.instance), vertex: conn.from.vertex },
          toPart: remap(conn.toPart),
        });
      }
    }
    return all;
  }, [step, previewRepeats]);

  return (
    <group>
      {showOrigin ? <OriginGizmo size={modelRadius} /> : null}

      {resolved.map(({ instance, matrix, role }) => {
        if (role === "completed" && !showCompleted) return null;
        const part = meshes.get(instance.partKey);
        const meta = partsByKey.get(instance.partKey);
        if (!part || !meta) return null;

        // "vertex" mode: show handles on all parts so user can pick a source vertex.
        // "target" mode (pendingVertex set): hide handles so parts are directly clickable;
        //   PartObject still surfaces the one pending vertex regardless of showVertices.
        const instanceShowVertices = connectMode ? !pendingVertex : showVertices;

        // Resolve the engraving face: per-instance override, else the part default.
        const side = instance.engravingSide ?? part.engravingSide;
        const engravingGeometry =
          side === "bottom" ? part.engravingBottom : part.engravingTop;

        return (
          <PartObject
            key={instance.id}
            instanceId={instance.id}
            matrix={matrix}
            part={part}
            color={meta.color}
            label={instance.sheet}
            labelPosition={bboxCenter(meta.bbox)}
            showLabel={showLabels}
            showVertices={instanceShowVertices}
            showEngravings={showEngravings}
            engravingGeometry={engravingGeometry}
            handleSize={handleSize}
            selected={selectedSet.has(instance.id)}
            pendingVertex={pendingVertex}
            onPickVertex={handlePickVertex}
            onSelect={(additive) => onSelectInstance(instance.id, additive)}
          />
        );
      })}

      {step ? (
        <Connectors
          connections={connections}
          resolved={resolvedMap}
          meshes={meshes}
          handleSize={handleSize}
        />
      ) : null}

      {selectionHighlights.map(({ id, hl }) => (
        <InstanceHighlight key={`sel-${id}`} geometry={hl.geometry} matrix={hl.matrix} opacity={0.3} />
      ))}

      {hovered ? <InstanceHighlight geometry={hovered.geometry} matrix={hovered.matrix} opacity={0.5} /> : null}
    </group>
  );
}
