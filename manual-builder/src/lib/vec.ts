import type { Mat4, Vec3 } from "../types/model";
import type { UpAxis } from "../types/manual";

export const ZERO: Vec3 = [0, 0, 0];

export function add(a: Vec3, b: Vec3): Vec3 {
  return [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
}

export function sub(a: Vec3, b: Vec3): Vec3 {
  return [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
}

export function scale(a: Vec3, s: number): Vec3 {
  return [a[0] * s, a[1] * s, a[2] * s];
}

export function dot(a: Vec3, b: Vec3): number {
  return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
}

export function cross(a: Vec3, b: Vec3): Vec3 {
  return [
    a[1] * b[2] - a[2] * b[1],
    a[2] * b[0] - a[0] * b[2],
    a[0] * b[1] - a[1] * b[0],
  ];
}

export function length(a: Vec3): number {
  return Math.hypot(a[0], a[1], a[2]);
}

export function normalize(a: Vec3): Vec3 {
  const len = length(a);
  return len < 1e-9 ? [0, 0, 0] : [a[0] / len, a[1] / len, a[2] / len];
}

export const DEG2RAD = Math.PI / 180;
export const RAD2DEG = 180 / Math.PI;

export function upVector(axis: UpAxis): Vec3 {
  if (axis === "x") return [1, 0, 0];
  if (axis === "y") return [0, 1, 0];
  return [0, 0, 1];
}

/** Apply a column-major Mat4 to a point (w = 1). */
export function applyMatrix(m: Mat4, v: Vec3): Vec3 {
  return [
    m[0] * v[0] + m[4] * v[1] + m[8] * v[2] + m[12],
    m[1] * v[0] + m[5] * v[1] + m[9] * v[2] + m[13],
    m[2] * v[0] + m[6] * v[1] + m[10] * v[2] + m[14],
  ];
}

/** Apply only the rotational part of a column-major Mat4 to a direction (w = 0). */
export function transformDirection(m: Mat4, v: Vec3): Vec3 {
  return normalize([
    m[0] * v[0] + m[4] * v[1] + m[8] * v[2],
    m[1] * v[0] + m[5] * v[1] + m[9] * v[2],
    m[2] * v[0] + m[6] * v[1] + m[10] * v[2],
  ]);
}

/**
 * Apply the inverse rotation of a column-major Mat4 to a direction.
 * For orthogonal (rotation-only) matrices, inverse = transpose of 3×3 block,
 * so we multiply by rows instead of columns.
 */
export function inverseTransformDirection(m: Mat4, v: Vec3): Vec3 {
  return normalize([
    m[0] * v[0] + m[1] * v[1] + m[2] * v[2],
    m[4] * v[0] + m[5] * v[1] + m[6] * v[2],
    m[8] * v[0] + m[9] * v[1] + m[10] * v[2],
  ]);
}

/** Translate a matrix's position columns by a world-space offset (immutably). */
export function translateMatrix(m: Mat4, offset: Vec3): Mat4 {
  const out = m.slice();
  out[12] += offset[0];
  out[13] += offset[1];
  out[14] += offset[2];
  return out;
}
