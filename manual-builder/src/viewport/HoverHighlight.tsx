import { useLayoutEffect, useRef } from "react";
import * as THREE from "three";

import type { Mat4 } from "../types/model";

interface Props {
  geometry: THREE.BufferGeometry;
  matrix: Mat4;
}

const HIGHLIGHT = "#f59e0b";

/**
 * A bright, depth-test-disabled overlay of a part used to highlight the instance
 * hovered in the Parts list. Because depth testing is off and it renders last, it
 * shows through other geometry — visible even when the part is occluded.
 */
export function HoverHighlight({ geometry, matrix }: Props) {
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
          color={HIGHLIGHT}
          transparent
          opacity={0.45}
          depthTest={false}
          depthWrite={false}
        />
      </mesh>
    </group>
  );
}
