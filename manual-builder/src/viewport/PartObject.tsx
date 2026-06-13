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
  showEngravings: boolean;
  /** The engraving geometry to render for this instance (side already resolved). */
  engravingGeometry: THREE.BufferGeometry | null;
  /** Local-space mirror to preview overlay flip_horizontal/vertical; null = none. */
  engravingFlipMatrix?: Mat4 | null;
  handleSize: number;
  selected: boolean;
  pendingVertex: VertexRef | null;
  onPickVertex: (ref: VertexRef) => void;
  /** `additive` is true when Cmd/Ctrl is held (toggle into the multi-selection). */
  onSelect: (additive: boolean) => void;
}

const HIGHLIGHT = "#f59e0b";
const IDENTITY16 = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];

/** Engraving line segments, optionally mirrored (local) to preview overlay flips. */
function EngravingLines({
  geometry,
  flipMatrix,
}: {
  geometry: THREE.BufferGeometry;
  flipMatrix: Mat4 | null;
}) {
  const ref = useRef<THREE.Group>(null);
  useLayoutEffect(() => {
    const g = ref.current;
    if (!g) return;
    g.matrixAutoUpdate = false;
    g.matrix.fromArray(flipMatrix ?? IDENTITY16);
    g.matrixWorldNeedsUpdate = true;
  }, [flipMatrix]);
  return (
    <group ref={ref}>
      <lineSegments geometry={geometry} renderOrder={2}>
        <lineBasicMaterial color="#1a1a2e" />
      </lineSegments>
    </group>
  );
}

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
  showEngravings,
  engravingGeometry,
  engravingFlipMatrix,
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
          onSelect(e.metaKey || e.ctrlKey);
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

      {showEngravings && engravingGeometry ? (
        <EngravingLines geometry={engravingGeometry} flipMatrix={engravingFlipMatrix ?? null} />
      ) : null}

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
