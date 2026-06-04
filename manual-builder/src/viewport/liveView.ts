import type { ViewSettings } from "../types/manual";

/**
 * A tiny mutable channel holding the camera's current orientation. The camera
 * rig keeps it up to date as the user orbits; the inspector reads it for the
 * "Capture current view" action. This avoids threading camera refs through the
 * FlexLayout component tree.
 */
export const liveView: ViewSettings = { azimuthDeg: 45, elevationDeg: 35.264, zoom: 1 };

export function captureLiveView(): ViewSettings {
  return { ...liveView };
}
