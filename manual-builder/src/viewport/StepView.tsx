import { Canvas } from "@react-three/fiber";

import { useAppStore } from "../store/useAppStore";
import { CameraRig } from "./CameraRig";
import { Lights } from "./Lights";
import { useMeshContext } from "./MeshProvider";
import { StepScene } from "./StepScene";
import { useViewportData } from "./useViewportData";

const noop = () => {};

/**
 * A small, persistent preview locked to the selected step's saved view. It is
 * non-interactive — the camera always reflects exactly what is stored, so it
 * shows the actual manual framing regardless of how the freeform view is moved.
 */
export function StepView() {
  const { model, manual, ui, target, radius, stepIndex, step, view, upAxis } = useViewportData();
  const { meshes, ready } = useMeshContext();
  const selectedInstanceId = useAppStore((s) => s.selectedInstanceId);

  if (!model || !manual) return <div className="panel-empty">No model loaded.</div>;

  return (
    <div className="viewport-root viewport-root--mini">
      <Canvas
        orthographic
        camera={{ position: [200, 200, 200], zoom: 1, near: 0.01, far: 100000, up: [0, 0, 1] }}
        gl={{ antialias: true }}
      >
        <Lights />
        <CameraRig view={view} upAxis={upAxis} target={target} radius={radius} interactive={false} />
        {ready ? (
          <StepScene
            model={model}
            manual={manual}
            stepIndex={stepIndex}
            meshes={meshes}
            modelRadius={radius}
            showLabels={ui.showLabels}
            showVertices={false}
            showCompleted={ui.showCompleted}
            showOrigin={ui.showOrigin}
            connectMode={false}
            pendingVertex={null}
            selectedInstanceId={selectedInstanceId}
            explodeScale={1}
            previewRepeats={false}
            onPickVertex={noop}
            onSelectInstance={noop}
          />
        ) : null}
      </Canvas>
      <div className="viewport-hud">
        {step ? (
          <span className="hud-step">{step.description.trim() || `Step ${stepIndex + 1}`}</span>
        ) : (
          <span>Full assembly</span>
        )}
      </div>
    </div>
  );
}
