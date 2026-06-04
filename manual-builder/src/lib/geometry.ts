import * as THREE from "three";
import type { BBox, Mat4, MeshData, Vec3 } from "../types/model";
import { applyMatrix, dot, normalize, sub, transformDirection } from "./vec";

/** Build a renderable BufferGeometry from an exported mesh payload. */
export function buildGeometry(mesh: MeshData): THREE.BufferGeometry {
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(mesh.positions, 3));
  geometry.setIndex(mesh.indices);
  geometry.computeVertexNormals();
  geometry.computeBoundingSphere();
  return geometry;
}

export function bboxCenter(bbox: BBox | null): Vec3 {
  if (!bbox) return [0, 0, 0];
  return [
    (bbox.min[0] + bbox.max[0]) / 2,
    (bbox.min[1] + bbox.max[1]) / 2,
    (bbox.min[2] + bbox.max[2]) / 2,
  ];
}

/**
 * Find up to 4 vertex indices on the attachment face of a (typically rectangular)
 * paper part — the flat face that faces toward the assembly when exploded.
 *
 * Strategy:
 *  1. The thickness axis = smallest bbox dimension (material thickness).
 *  2. The attachment face = the flat face whose normal is opposite to the local
 *     explode direction (i.e., the face the part sits against when assembled).
 *  3. Among vertices on that face, find the 4 extremes of the 2D bounding
 *     rectangle in the face plane — one per quadrant corner.
 */
export function autoConnectVertices(
  vertices: Vec3[],
  bbox: BBox,
  localExplodeDir: Vec3,
): number[] {
  const dims = [bbox.max[0] - bbox.min[0], bbox.max[1] - bbox.min[1], bbox.max[2] - bbox.min[2]];
  const thickAxis = dims[0] <= dims[1] && dims[0] <= dims[2] ? 0 : dims[1] <= dims[2] ? 1 : 2;
  const [fa, fb] = [0, 1, 2].filter((i) => i !== thickAxis) as [number, number];

  // Attachment face is opposite to the explode direction along the thick axis.
  const faceCoord =
    localExplodeDir[thickAxis] >= 0 ? bbox.min[thickAxis] : bbox.max[thickAxis];
  const faceTol = Math.max(dims[thickAxis] * 0.15, 0.05);

  const faceVerts = vertices
    .map((v, i) => ({ v, i }))
    .filter(({ v }) => Math.abs(v[thickAxis] - faceCoord) <= faceTol);

  if (faceVerts.length === 0) return [];

  const minA = Math.min(...faceVerts.map(({ v }) => v[fa]));
  const maxA = Math.max(...faceVerts.map(({ v }) => v[fa]));
  const minB = Math.min(...faceVerts.map(({ v }) => v[fb]));
  const maxB = Math.max(...faceVerts.map(({ v }) => v[fb]));

  // One closest vertex per bounding-box quadrant corner.
  const targets: [number, number][] = [
    [minA, minB],
    [minA, maxB],
    [maxA, minB],
    [maxA, maxB],
  ];
  const seen = new Set<number>();
  const result: number[] = [];
  for (const [ta, tb] of targets) {
    let best = -1;
    let bestDist = Infinity;
    for (const { v, i } of faceVerts) {
      const d = (v[fa] - ta) ** 2 + (v[fb] - tb) ** 2;
      if (d < bestDist) {
        bestDist = d;
        best = i;
      }
    }
    if (best >= 0 && !seen.has(best)) {
      seen.add(best);
      result.push(best);
    }
  }
  return result;
}

/**
 * Pick the world-space normal of a part's flattest face and orient it away from
 * the assembly center. The thinnest local axis = the stacking / thickness axis;
 * its face normal is the natural explode direction for a flat sheet part.
 */
export function smartExplodeDirection(
  instanceMatrix: Mat4,
  partBbox: BBox,
  assemblyBbox: BBox | null,
): Vec3 {
  const dx = partBbox.max[0] - partBbox.min[0];
  const dy = partBbox.max[1] - partBbox.min[1];
  const dz = partBbox.max[2] - partBbox.min[2];

  // Local axis with the smallest extent → the thickness / flat-face normal.
  let localNormal: Vec3;
  if (dx <= dy && dx <= dz) localNormal = [1, 0, 0];
  else if (dy <= dz) localNormal = [0, 1, 0];
  else localNormal = [0, 0, 1];

  // Rotate into world space (no translation).
  const worldNormal = transformDirection(instanceMatrix, localNormal);

  // Flip so the direction points away from the assembly center.
  const partCenter = applyMatrix(instanceMatrix, bboxCenter(partBbox));
  const assemblyCenter = bboxCenter(assemblyBbox);
  const outward = normalize(sub(partCenter, assemblyCenter));
  return dot(worldNormal, outward) >= 0 ? worldNormal : [-worldNormal[0], -worldNormal[1], -worldNormal[2]];
}

export function bboxRadius(bbox: BBox | null): number {
  if (!bbox) return 100;
  const dx = bbox.max[0] - bbox.min[0];
  const dy = bbox.max[1] - bbox.min[1];
  const dz = bbox.max[2] - bbox.min[2];
  return 0.5 * Math.hypot(dx, dy, dz);
}
