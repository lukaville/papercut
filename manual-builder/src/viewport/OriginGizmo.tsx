import { useEffect, useMemo } from "react";
import * as THREE from "three";

/**
 * World-origin helper: X (red), Y (green), Z (blue) arrows from (0,0,0) plus a
 * small center marker. Sized relative to the model so it reads at any scale.
 */
export function OriginGizmo({ size }: { size: number }) {
  const length = Math.max(size, 1);
  const headLength = length * 0.08;
  const headWidth = headLength * 0.6;

  const arrows = useMemo(() => {
    const make = (dir: THREE.Vector3, color: number) =>
      new THREE.ArrowHelper(dir, new THREE.Vector3(0, 0, 0), length, color, headLength, headWidth);
    return [
      make(new THREE.Vector3(1, 0, 0), 0xef4444),
      make(new THREE.Vector3(0, 1, 0), 0x22c55e),
      make(new THREE.Vector3(0, 0, 1), 0x3b82f6),
    ];
  }, [length, headLength, headWidth]);

  useEffect(() => () => arrows.forEach((a) => a.dispose()), [arrows]);

  return (
    <group>
      {arrows.map((arrow, i) => (
        <primitive key={i} object={arrow} />
      ))}
      <mesh>
        <sphereGeometry args={[length * 0.03, 16, 16]} />
        <meshBasicMaterial color="#111827" />
      </mesh>
    </group>
  );
}
