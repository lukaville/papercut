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
import type { Mat4 } from "../types/model";

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
