import { useMemo } from "react";

import { bboxCenter, bboxRadius } from "../lib/geometry";
import { useAppStore } from "../store/useAppStore";
import {
  effectiveView,
  type ManualDocument,
  type Step,
  type ViewSettings,
} from "../types/manual";
import type { ModelData } from "../types/model";

const FALLBACK_VIEW: ViewSettings = { azimuthDeg: 45, elevationDeg: 35.264, zoom: 1 };

export interface ViewportData {
  model: ModelData | null;
  manual: ManualDocument | null;
  ui: ReturnType<typeof useAppStore.getState>["ui"];
  target: [number, number, number];
  radius: number;
  stepIndex: number;
  step: Step | null;
  /** Effective view of the selected step (or document/fallback default). */
  view: ViewSettings;
  upAxis: "x" | "y" | "z";
}

/** Shared scene framing + selected-step data used by both viewports. */
export function useViewportData(): ViewportData {
  const model = useAppStore((s) => s.model);
  const manual = useAppStore((s) => s.manual);
  const selectedStepId = useAppStore((s) => s.selectedStepId);
  const ui = useAppStore((s) => s.ui);

  const target = useMemo(() => bboxCenter(model?.bounds ?? null), [model]);
  const radius = useMemo(() => bboxRadius(model?.bounds ?? null), [model]);

  const stepIndex =
    manual && selectedStepId ? manual.steps.findIndex((s) => s.id === selectedStepId) : -1;
  const step = manual && stepIndex >= 0 ? manual.steps[stepIndex] : null;
  const view = manual
    ? step
      ? effectiveView(step, manual.defaults)
      : manual.defaults.view
    : FALLBACK_VIEW;
  const upAxis = manual?.defaults.upAxis ?? "z";

  return { model, manual, ui, target, radius, stepIndex, step, view, upAxis };
}
