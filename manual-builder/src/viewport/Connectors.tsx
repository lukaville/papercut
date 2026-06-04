import { useMemo } from "react";
import { Line } from "@react-three/drei";
import * as THREE from "three";

import { applyMatrix } from "../lib/vec";
import type { ResolvedInstance } from "../lib/stepGeometry";
import { useAppStore } from "../store/useAppStore";
import type { Connection } from "../types/manual";
import type { Vec3 } from "../types/model";
import { ConstantSphere } from "./ConstantSphere";
import type { PartGeometry } from "./useMeshes";

interface Props {
  connections: Connection[];
  resolved: Map<string, ResolvedInstance>;
  meshes: Map<string, PartGeometry>;
  handleSize: number;
}

interface Endpoint {
  from: Vec3;
  to: Vec3;
  warning: boolean;
}

const DOUBLE_SIDED = new THREE.MeshBasicMaterial({ side: THREE.DoubleSide });

/** Compute the world-space explosion offset of an instance (zero if not exploded). */
function explosionVec(inst: ResolvedInstance, pg: PartGeometry): Vec3 {
  const v = pg.mesh.vertices[0];
  if (!v) return [0, 0, 0];
  const cur = applyMatrix(inst.matrix, v);
  const asm = applyMatrix(inst.instance.matrix, v);
  return [cur[0] - asm[0], cur[1] - asm[1], cur[2] - asm[2]];
}

/**
 * Find the first hit on `tempMesh` (which must have matrixWorld pre-set) from
 * `origin` in `dir` or its reverse, within `threshold` mm. Returns null if
 * the assembled vertex doesn't lie on the target surface.
 */
function findContactPoint(
  origin: THREE.Vector3,
  dir: THREE.Vector3,
  tempMesh: THREE.Mesh,
  threshold: number,
): THREE.Vector3 | null {
  for (const d of [dir, dir.clone().negate()]) {
    const rc = new THREE.Raycaster(origin, d);
    const hits = rc.intersectObject(tempMesh, false);
    const h = hits.find((x) => x.distance <= threshold);
    if (h) return h.point.clone();
  }
  return null;
}

/** Dashed leader lines from exploded parts to their assembled contact point on the target. */
export function Connectors({ connections, resolved, meshes, handleSize }: Props) {
  const hoveredConnectionId = useAppStore((s) => s.hoveredConnectionId);

  const endpoints = useMemo(() => {
    const result = new Map<string, Endpoint>();
    // Threshold for "vertex lies on surface": allow small numerical gap.
    const threshold = Math.max(handleSize * 2, 2.0);

    for (const conn of connections) {
      const fromInst = resolved.get(conn.from.instance);
      if (!fromInst) continue;
      const fromPg = meshes.get(fromInst.instance.partKey);
      const local = fromPg?.mesh.vertices[conn.from.vertex];
      if (!local) continue;

      const fromCurrent: Vec3 = applyMatrix(fromInst.matrix, local);
      const pAssembled: Vec3 = applyMatrix(fromInst.instance.matrix, local);

      const toInst = resolved.get(conn.toPart);
      if (!toInst) { result.set(conn.id, { from: fromCurrent, to: pAssembled, warning: true }); continue; }
      const toPg = meshes.get(toInst.instance.partKey);
      if (!toPg) { result.set(conn.id, { from: fromCurrent, to: pAssembled, warning: true }); continue; }

      // World-space explosion offsets for source and target.
      const sVec = explosionVec(fromInst, fromPg);
      const tVec = explosionVec(toInst, toPg);

      const sDist = Math.sqrt(sVec[0] ** 2 + sVec[1] ** 2 + sVec[2] ** 2);
      const tDist = Math.sqrt(tVec[0] ** 2 + tVec[1] ** 2 + tVec[2] ** 2);

      // Explosion direction for raycasting: prefer source; fall back to target.
      // This covers both (source exploded → target assembled) and the reverse.
      let rayDir: THREE.Vector3;
      if (sDist > 0.01) {
        rayDir = new THREE.Vector3(sVec[0] / sDist, sVec[1] / sDist, sVec[2] / sDist);
      } else if (tDist > 0.01) {
        rayDir = new THREE.Vector3(tVec[0] / tDist, tVec[1] / tDist, tVec[2] / tDist);
      } else {
        // Neither part is exploded — nothing meaningful to draw.
        result.set(conn.id, { from: fromCurrent, to: pAssembled, warning: true });
        continue;
      }

      // Raycast against the ASSEMBLED target to find where pAssembled contacts it.
      const tempMesh = new THREE.Mesh(toPg.geometry, DOUBLE_SIDED);
      tempMesh.matrixWorld.fromArray(toInst.instance.matrix);

      const pVec = new THREE.Vector3(pAssembled[0], pAssembled[1], pAssembled[2]);
      const qAssembled = findContactPoint(pVec, rayDir, tempMesh, threshold);

      // Translate the assembled contact point to the target's current (possibly
      // exploded) position by adding the target's explosion offset.
      const q: Vec3 = qAssembled
        ? [qAssembled.x, qAssembled.y, qAssembled.z]
        : pAssembled;
      const to: Vec3 = [q[0] + tVec[0], q[1] + tVec[1], q[2] + tVec[2]];

      result.set(conn.id, { from: fromCurrent, to, warning: qAssembled === null });
    }

    return result;
  }, [connections, resolved, meshes, handleSize]);

  return (
    <group>
      {connections.map((conn) => {
        const ep = endpoints.get(conn.id);
        if (!ep) return null;
        const { from, to, warning } = ep;

        const hovered = conn.id === hoveredConnectionId;
        const color = warning ? "#f59e0b" : hovered ? "#f97316" : "#ef4444";
        const dimColor = warning ? "#d97706" : hovered ? "#ea580c" : "#b91c1c";

        const hasLine = from[0] !== to[0] || from[1] !== to[1] || from[2] !== to[2];

        return (
          <group key={conn.id}>
            {hasLine ? (
              <Line
                points={[from, to]}
                color={color}
                lineWidth={hovered ? 2.5 : 1.5}
                dashed={!hovered}
                dashSize={handleSize * 0.6}
                gapSize={handleSize * 0.4}
              />
            ) : null}
            <ConstantSphere position={from} screenPixels={hovered ? 5 : 3} color={color} />
            {hasLine ? (
              <ConstantSphere position={to} screenPixels={hovered ? 5 : 3} color={dimColor} />
            ) : null}
          </group>
        );
      })}
    </group>
  );
}
