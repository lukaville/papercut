import { useLayoutEffect, useRef } from "react";
import * as THREE from "three";

import type { Mat4 } from "../types/model";

interface Props {
  geometry: THREE.BufferGeometry;
  matrix: Mat4;
  color?: string;
  opacity?: number;
}

const HIGHLIGHT = "#f59e0b";

/**
 * A bright, depth-test-disabled overlay of a part, used to highlight instances
 * that are hovered or selected in the Parts list. Because depth testing is off
 * and it renders last, it shows through other geometry — so the part stays
 * visible even when occluded or not otherwise drawn in the current step.
 */
export function InstanceHighlight({ geometry, matrix, color = HIGHLIGHT, opacity = 0.45 }: Props) {
  const groupRef = useRef<THREE.Group>(null);

  useLayoutEffect(() => {
    const group = groupRef.current;
    if (!group) return;
    group.matrixAutoUpdate = false;
    group.matrix.fromArray(matrix);
    group.matrixWorldNeedsUpdate = true;
  }, [matrix]);

  return (
    <group ref={groupRef}>
      <mesh geometry={geometry} renderOrder={999}>
        <meshBasicMaterial
          color={color}
          transparent
          opacity={opacity}
          depthTest={false}
          depthWrite={false}
        />
      </mesh>
    </group>
  );
}
