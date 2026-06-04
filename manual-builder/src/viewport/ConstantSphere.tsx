import { useRef, useState } from "react";
import type { ThreeEvent } from "@react-three/fiber";
import { useFrame, useThree } from "@react-three/fiber";
import * as THREE from "three";

import type { Vec3 } from "../types/model";

interface Props {
  position: Vec3;
  screenPixels: number;
  color: string;
  onPointerDown?: (e: ThreeEvent<PointerEvent>) => void;
}

/**
 * A sphere that stays a constant size in screen pixels regardless of camera zoom.
 * Rendered in two passes so it appears semi-transparent when occluded by geometry
 * and fully opaque when in front. Grows slightly on hover and exposes a larger
 * invisible hit target so vertices are easy to click precisely.
 */
export function ConstantSphere({ position, screenPixels, color, onPointerDown }: Props) {
  const groupRef = useRef<THREE.Group>(null);
  const [hovered, setHovered] = useState(false);
  const { camera, size } = useThree();

  useFrame(() => {
    if (!groupRef.current) return;
    const orth = camera as THREE.OrthographicCamera;
    const unitsPerPx = (orth.top - orth.bottom) / (orth.zoom * size.height);
    groupRef.current.scale.setScalar(unitsPerPx * screenPixels * (hovered ? 1.6 : 1));
  });

  return (
    <group ref={groupRef} position={position}>
      {/* Invisible hit target — 2.5× radius so clicking near the sphere works */}
      <mesh
        renderOrder={10}
        onPointerDown={onPointerDown}
        onClick={(e) => e.stopPropagation()}
        onPointerOver={(e) => { e.stopPropagation(); setHovered(true); }}
        onPointerOut={() => setHovered(false)}
      >
        <sphereGeometry args={[2.5, 8, 8]} />
        <meshBasicMaterial transparent opacity={0} depthTest={false} depthWrite={false} />
      </mesh>
      {/* Pass 1: draws behind geometry at low opacity */}
      <mesh renderOrder={9}>
        <sphereGeometry args={[1, 8, 8]} />
        <meshBasicMaterial
          color={hovered ? "#ffffff" : color}
          transparent
          opacity={hovered ? 0.4 : 0.2}
          depthTest={false}
          depthWrite={false}
        />
      </mesh>
      {/* Pass 2: draws only where sphere is in front of geometry, fully opaque */}
      <mesh renderOrder={10}>
        <sphereGeometry args={[1, 8, 8]} />
        <meshBasicMaterial color={hovered ? "#ffffff" : color} depthTest={true} depthWrite={false} />
      </mesh>
    </group>
  );
}
