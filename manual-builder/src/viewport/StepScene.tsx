import { useCallback, useMemo } from "react";

import { bboxCenter } from "../lib/geometry";
import { resolveStepInstances, resolvedById } from "../lib/stepGeometry";
import type { Connection, ManualDocument, VertexRef } from "../types/manual";
import type { ModelData, ModelPart } from "../types/model";
import { Connectors } from "./Connectors";
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
  pendingVertex: VertexRef | null;
  selectedInstanceId: string | null;
  explodeScale: number;
  /** Show all copies of a repeated step (preview) vs. only the primary. */
  previewRepeats: boolean;
  onPickVertex: (ref: VertexRef) => void;
  onSelectInstance: (id: string) => void;
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
  pendingVertex,
  selectedInstanceId,
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
            handleSize={handleSize}
            selected={instance.id === selectedInstanceId}
            pendingVertex={pendingVertex}
            onPickVertex={handlePickVertex}
            onSelect={() => onSelectInstance(instance.id)}
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
    </group>
  );
}
