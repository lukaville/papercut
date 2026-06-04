import type { Vec3 } from "../types/model";
import type { UpAxis, ViewSettings } from "../types/manual";
import { add, cross, DEG2RAD, dot, normalize, RAD2DEG, scale, sub, upVector } from "./vec";

/**
 * Camera orientation expressed relative to an arbitrary up axis (the model's
 * "up", typically CAD Z). Azimuth rotates around the up axis; elevation tilts
 * from the horizontal plane toward up.
 */

interface Basis {
  up: Vec3;
  /** Reference horizontal axis (azimuth 0). */
  fwd: Vec3;
  /** Horizontal axis 90° from `fwd`. */
  right: Vec3;
}

function orthoBasis(axis: UpAxis): Basis {
  const up = upVector(axis);
  // Choose a reference not parallel to up.
  const ref: Vec3 = Math.abs(up[0]) < 0.9 ? [1, 0, 0] : [0, 1, 0];
  const right = normalize(cross(up, ref));
  const fwd = normalize(cross(right, up));
  return { up, fwd, right };
}

/** Unit direction pointing from the target toward the camera. */
export function viewDirection(view: ViewSettings, axis: UpAxis): Vec3 {
  const { up, fwd, right } = orthoBasis(axis);
  const a = view.azimuthDeg * DEG2RAD;
  const e = view.elevationDeg * DEG2RAD;
  const horizontal = add(scale(fwd, Math.cos(a)), scale(right, Math.sin(a)));
  return normalize(add(scale(horizontal, Math.cos(e)), scale(up, Math.sin(e))));
}

export interface CameraPose {
  position: Vec3;
  up: Vec3;
}

export function cameraPose(
  view: ViewSettings,
  axis: UpAxis,
  target: Vec3,
  distance: number,
): CameraPose {
  const dir = viewDirection(view, axis);
  return { position: add(target, scale(dir, distance)), up: upVector(axis) };
}

/** Recover azimuth/elevation from a camera position (inverse of `cameraPose`). */
export function viewFromCamera(
  position: Vec3,
  target: Vec3,
  axis: UpAxis,
  zoom: number,
): ViewSettings {
  const { up, fwd, right } = orthoBasis(axis);
  const dir = normalize(sub(position, target));
  const elevation = Math.asin(Math.max(-1, Math.min(1, dot(dir, up))));
  const horizontal = normalize(sub(dir, scale(up, dot(dir, up))));
  const azimuth = Math.atan2(dot(horizontal, right), dot(horizontal, fwd));
  return {
    azimuthDeg: round(azimuth * RAD2DEG),
    elevationDeg: round(elevation * RAD2DEG),
    zoom: round(zoom),
  };
}

function round(n: number): number {
  return Math.round(n * 1000) / 1000;
}
