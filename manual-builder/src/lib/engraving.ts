/**
 * Engraving geometry helpers.
 *
 * Converts the 2D DXF-coordinate SVG paths produced by the Python pipeline into
 * 3D LineSegments geometry that sits on the correct flat face of a part.
 *
 * ## Coordinate mapping
 *
 * The engraving SVG lives in the same 2D frame as the part's exported cut
 * profile (bottom-left at the origin). The Python exporter records the exact
 * `transform` that maps that 2D frame back into the part's local 3D space — it
 * is the inverse of the orientation + bottom-left translation applied in
 * `dxf_exporter.export_part_dxf`. Using it avoids any guessing about OCC's
 * internal axis conventions, so engravings can never end up rotated 90°.
 *
 * `side` selects which face the lines sit on; the geometry is nudged slightly
 * off the surface (along the face normal) to avoid z-fighting.
 */

import * as THREE from "three";
import type { BBox, Mat4 } from "../types/model";

/** Householder reflection about the plane through `center` perpendicular to `axis`. */
function reflectionMatrix(axis: THREE.Vector3, center: THREE.Vector3): THREE.Matrix4 {
  const a = axis.clone().normalize();
  const { x: ax, y: ay, z: az } = a;
  const d = 2 * center.dot(a);
  // Linear part L = I - 2·aaᵀ ; translation t = 2(C·a)·a keeps `center` fixed.
  return new THREE.Matrix4().set(
    1 - 2 * ax * ax, -2 * ax * ay, -2 * ax * az, d * ax,
    -2 * ay * ax, 1 - 2 * ay * ay, -2 * ay * az, d * ay,
    -2 * az * ax, -2 * az * ay, 1 - 2 * az * az, d * az,
    0, 0, 0, 1,
  );
}

/**
 * Local-space matrix that mirrors a part's engraving about its centre to preview
 * `flip_horizontal` / `flip_vertical` without reprocessing. The flips are defined
 * in the 2D DXF frame (X = horizontal, Y = vertical); `transform` gives those axes'
 * directions in the part's local frame. Returns null when neither flip is active.
 *
 * This is an approximation: the Python pipeline re-runs an alignment search after
 * flipping, so for strongly asymmetric outlines the reprocessed result can differ.
 */
export function engravingFlipMatrix(
  transform: Mat4,
  bbox: BBox,
  flipH: boolean,
  flipV: boolean,
): Mat4 | null {
  if (!flipH && !flipV) return null;
  const center = new THREE.Vector3(
    (bbox.min[0] + bbox.max[0]) / 2,
    (bbox.min[1] + bbox.max[1]) / 2,
    (bbox.min[2] + bbox.max[2]) / 2,
  );
  const m = new THREE.Matrix4();
  if (flipH) m.premultiply(reflectionMatrix(new THREE.Vector3(transform[0], transform[1], transform[2]), center));
  if (flipV) m.premultiply(reflectionMatrix(new THREE.Vector3(transform[4], transform[5], transform[6]), center));
  return m.toArray();
}

/** A single line segment in 2-D DXF space. */
type Seg = [[number, number], [number, number]];

/**
 * Parse "M x,y L x,y M x,y L x,y ..." into an array of line segments.
 * Consecutive L commands after a single M produce a polyline of segments.
 */
function parseSvg(svg: string): Seg[] {
  const segs: Seg[] = [];
  const tokens = svg.trim().split(/\s+/);
  let pen: [number, number] | null = null;

  for (let i = 0; i < tokens.length; i++) {
    const cmd = tokens[i];
    if (cmd === "M") {
      const [x, y] = tokens[++i].split(",").map(Number);
      pen = [x, y];
    } else if (cmd === "L") {
      const [x, y] = tokens[++i].split(",").map(Number);
      if (pen) {
        segs.push([pen, [x, y]]);
        pen = [x, y];
      }
    }
  }
  return segs;
}

/** Apply a column-major 4x4 matrix to a 3-D point (w = 1). */
function applyMat4(m: Mat4, x: number, y: number, z: number): [number, number, number] {
  return [
    m[0] * x + m[4] * y + m[8] * z + m[12],
    m[1] * x + m[5] * y + m[9] * z + m[13],
    m[2] * x + m[6] * y + m[10] * z + m[14],
  ];
}

/**
 * Build a `THREE.BufferGeometry` of `LineSegments` for the engraving, in part
 * local space. Should be placed inside the same `<group>` that carries the
 * instance matrix so world placement is automatic.
 *
 * @param transform  Column-major 4x4 mapping 2D DXF coords -> local 3D.
 * @param side       Which face the engraving belongs to.
 * @param thickness  Material thickness (mm); used to offset the bottom face.
 */
export function buildEngravingGeometry(
  svg: string,
  transform: Mat4,
  side: "top" | "bottom",
  thickness: number,
): THREE.BufferGeometry {
  // In the DXF frame the cut profile (top face) lies at z = 0 and the body
  // extends to z = -thickness. Push the lines a hair off the relevant face,
  // away from the body, so they don't z-fight with the mesh.
  const eps = Math.max(thickness * 0.1, 0.02);
  const zEng = side === "bottom" ? -(thickness + eps) : eps;

  const segs = parseSvg(svg);
  const positions: number[] = [];

  for (const [p1, p2] of segs) {
    positions.push(...applyMat4(transform, p1[0], p1[1], zEng));
    positions.push(...applyMat4(transform, p2[0], p2[1], zEng));
  }

  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  return geo;
}
