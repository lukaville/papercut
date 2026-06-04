import { useLayoutEffect, useRef } from "react";
import type { ThreeEvent } from "@react-three/fiber";
import { Edges, Html } from "@react-three/drei";
import * as THREE from "three";

import { partColor } from "../lib/color";
import type { VertexRef } from "../types/manual";
import type { Mat4, Vec3 } from "../types/model";
import { ConstantSphere } from "./ConstantSphere";
import type { PartGeometry } from "./useMeshes";

interface Props {
  instanceId: string;
  matrix: Mat4;
  part: PartGeometry;
  color: string;
  label: string | null;
  labelPosition: Vec3;
  showLabel: boolean;
  showVertices: boolean;
  handleSize: number;
  selected: boolean;
  pendingVertex: VertexRef | null;
  onPickVertex: (ref: VertexRef) => void;
  onSelect: () => void;
}

const HIGHLIGHT = "#f59e0b";

/** One placed part: shaded mesh + crisp edges, optional label and vertex handles. */
export function PartObject({
  instanceId,
  matrix,
  part,
  color,
  label,
  labelPosition,
  showLabel,
  showVertices,
  handleSize: _handleSize,
  selected,
  pendingVertex,
  onPickVertex,
  onSelect,
}: Props) {
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
      <mesh
        geometry={part.geometry}
        renderOrder={1}
        onClick={(e: ThreeEvent<MouseEvent>) => {
          e.stopPropagation();
          onSelect();
        }}
      >
        <meshStandardMaterial
          color={partColor(color)}
          roughness={0.7}
          metalness={0.04}
          emissive={selected ? HIGHLIGHT : "#000000"}
          emissiveIntensity={selected ? 0.3 : 0}
        />
        <Edges threshold={18} color={selected ? HIGHLIGHT : "#0f172a"} />
      </mesh>

      {showLabel && label ? (
        <Html position={labelPosition} center distanceFactor={undefined} zIndexRange={[10, 0]}>
          <div className="part-badge">{label}</div>
        </Html>
      ) : null}

      {part.mesh.vertices.map((v, index) => {
        const isPending =
          pendingVertex?.instance === instanceId && pendingVertex?.vertex === index;
        if (!showVertices && !isPending) return null;
        return (
          <ConstantSphere
            key={index}
            position={v}
            screenPixels={isPending ? 5 : 3}
            color={isPending ? "#f97316" : "#2563eb"}
            onPointerDown={(e: ThreeEvent<PointerEvent>) => {
              e.stopPropagation();
              onPickVertex({ instance: instanceId, vertex: index });
            }}
          />
        );
      })}
    </group>
  );
}
