import { useEffect } from "react";
import { Canvas } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import * as THREE from "three";

import { useAppStore } from "../store/useAppStore";
import { isRepeated, repeatCount } from "../types/manual";
import { CameraRig } from "./CameraRig";
import { Lights } from "./Lights";
import { useMeshContext } from "./MeshProvider";
import { NavCube } from "./NavCube";
import { StepScene } from "./StepScene";
import { TrackpadControls } from "./TrackpadControls";
import { useViewportData } from "./useViewportData";

// Any drag rotates (incl. a two-finger trackpad click-drag = right button);
// panning and zooming are handled by TrackpadControls via wheel gestures.
const ROTATE_BUTTONS = {
  LEFT: THREE.MOUSE.ROTATE,
  MIDDLE: THREE.MOUSE.ROTATE,
  RIGHT: THREE.MOUSE.ROTATE,
};

/** The freeform viewport: orbit freely, with buttons to sync to/from the step view. */
export function Viewport() {
  const { model, manual, ui, target, radius, stepIndex, step, view, upAxis } = useViewportData();
  const { meshes, ready, error } = useMeshContext();

  const selectedInstanceId = useAppStore((s) => s.selectedInstanceId);
  const selectedInstanceIds = useAppStore((s) => s.selectedInstanceIds);
  const hoveredInstanceId = useAppStore((s) => s.hoveredInstanceId);
  const pendingVertex = useAppStore((s) => s.pendingVertex);
  const selectInstance = useAppStore((s) => s.selectInstance);
  const toggleInstanceSelection = useAppStore((s) => s.toggleInstanceSelection);
  const pickVertex = useAppStore((s) => s.pickVertex);
  const addConnection = useAppStore((s) => s.addConnection);
  const clearPendingVertex = useAppStore((s) => s.clearPendingVertex);
  const applyToken = useAppStore((s) => s.freeformApplyToken);
  const saveFreeformView = useAppStore((s) => s.saveFreeformView);
  const resetFreeformView = useAppStore((s) => s.resetFreeformView);
  const transientFreeformView = useAppStore((s) => s.transientFreeformView);
  const applyFreeformView = useAppStore((s) => s.applyFreeformView);
  const explodeScale = useAppStore((s) => s.explodeScale);
  const setUi = useAppStore((s) => s.setUi);

  useEffect(() => {
    if (!pendingVertex) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") clearPendingVertex();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [pendingVertex, clearPendingVertex]);

  if (!model || !manual) return <div className="panel-empty">No model loaded.</div>;

  // Explicit selection mode so all children can branch on it without re-deriving.
  const selectionMode = !ui.connectMode ? "normal"
    : pendingVertex ? "target"
    : "vertex";

  // In "vertex" sub-mode StepScene enables handles on added parts itself;
  // "target" sub-mode hides them so parts are directly clickable.
  const showVertices = ui.showVertices;

  const handleSelectInstance = (instanceId: string, additive: boolean) => {
    if (selectionMode === "target" && pendingVertex) {
      addConnection(pendingVertex, instanceId);
      clearPendingVertex();
    } else if (additive) {
      // Cmd/Ctrl+click toggles the part in/out of the multi-selection.
      toggleInstanceSelection(instanceId);
    } else {
      selectInstance(instanceId);
    }
  };

  return (
    <div className="viewport-root">
      <Canvas
        orthographic
        camera={{ position: [200, 200, 200], zoom: 1, near: 0.01, far: 100000, up: [0, 0, 1] }}
        dpr={[1, 2]}
        gl={{ antialias: true, powerPreference: "high-performance" }}
        onPointerMissed={() => { selectInstance(null); clearPendingVertex(); }}
      >
        <Lights />
        <CameraRig view={transientFreeformView ?? view} upAxis={upAxis} target={target} radius={radius} interactive applyKey={applyToken} />
        <OrbitControls
          makeDefault
          enableDamping
          dampingFactor={0.12}
          rotateSpeed={0.9}
          enableZoom={false}
          enablePan={false}
          mouseButtons={ROTATE_BUTTONS}
        />
        <TrackpadControls />
        <NavCube onClickView={applyFreeformView} />

        {ready ? (
          <StepScene
            model={model}
            manual={manual}
            stepIndex={stepIndex}
            meshes={meshes}
            modelRadius={radius}
            showLabels={ui.showLabels}
            showVertices={showVertices}
            showCompleted={ui.showCompleted}
            showOrigin={ui.showOrigin}
            connectMode={ui.connectMode}
            showEngravings={ui.showEngravings}
            pendingVertex={pendingVertex}
            selectedInstanceId={selectedInstanceId}
            selectedInstanceIds={selectedInstanceIds}
            hoveredInstanceId={hoveredInstanceId}
            explodeScale={explodeScale}
            previewRepeats={ui.previewRepeats}
            onPickVertex={pickVertex}
            onSelectInstance={handleSelectInstance}
          />
        ) : null}
      </Canvas>

      <div className="viewport-toolbar">
        <button
          className={`btn btn--small${ui.showEngravings ? " btn--primary" : ""}`}
          onClick={() => setUi({ showEngravings: !ui.showEngravings })}
          title="Toggle engraving lines"
        >
          ✍ Engravings
        </button>
        <button
          className="btn btn--small"
          disabled={!step}
          onClick={saveFreeformView}
          title="Save this camera as the step's view"
        >
          ⤓ Save as step view
        </button>
        <button
          className="btn btn--small"
          disabled={!step}
          onClick={resetFreeformView}
          title="Reset this camera to the step's view"
        >
          ⤒ Match step view
        </button>
        {step && isRepeated(step) ? (
          <button
            className={`btn btn--small${ui.previewRepeats ? " btn--primary" : ""}`}
            onClick={() => setUi({ previewRepeats: !ui.previewRepeats })}
            title="Toggle between the primary (manual view) and all copies (preview)"
          >
            {ui.previewRepeats ? `◉ Preview ×${repeatCount(step)}` : "○ Primary only"}
          </button>
        ) : null}
      </div>

      {!ready && !error ? <div className="viewport-overlay">Loading geometry…</div> : null}
      {error ? <div className="viewport-overlay viewport-overlay--error">{error}</div> : null}

      <div className="viewport-hud">
        {step ? (
          <span className="hud-step">{step.description.trim() || `Step ${stepIndex + 1}`}</span>
        ) : (
          <span>Full assembly</span>
        )}
        {selectionMode !== "normal" ? (
          <span className="hud-connect">
            {selectionMode === "target"
              ? "Connect mode · click the target part  (Esc to cancel)"
              : "Connect mode · click a vertex on a new part"}
          </span>
        ) : null}
      </div>
    </div>
  );
}
