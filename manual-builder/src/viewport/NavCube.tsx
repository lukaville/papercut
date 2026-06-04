import type { ThreeEvent } from "@react-three/fiber";
import { GizmoHelper, GizmoViewcube } from "@react-three/drei";

import { liveView } from "./liveView";
import type { ViewSettings } from "../types/manual";

// Face order for GizmoViewcube box geometry: [+X, -X, +Y, -Y, +Z, -Z].
// In Z-up with az=0→camera at +X:
//   +X = FRONT, -X = BACK, +Y = LEFT, -Y = RIGHT, +Z = TOP, -Z = BOTTOM
const FACES = ["Front", "Back", "Left", "Right", "Top", "Bottom"];

const RAD2DEG = 180 / Math.PI;

interface Props {
  onClickView: (view: ViewSettings) => void;
}

// Elevation is clamped away from ±90° to avoid gimbal lock: at exactly ±90 the
// camera's Z-up vector is collinear with the view direction, so lookAt leaves
// the camera roll undefined (inheriting whatever it was before = "rotated" look).
// 89° is imperceptible in orthographic projection but sidesteps the singularity.
// The azimuth is also canonicalised to 0° for these near-pole views so the
// top/bottom always faces the same canonical direction.
const MAX_EL = 89;

function directionToView(x: number, y: number, z: number, snap: boolean): ViewSettings {
  const len = Math.sqrt(x * x + y * y + z * z);
  if (len < 1e-6) return { azimuthDeg: 0, elevationDeg: 0, zoom: liveView.zoom };
  const nx = x / len, ny = y / len, nz = z / len;
  let az = Math.atan2(ny, nx) * RAD2DEG;
  let el = Math.asin(Math.max(-1, Math.min(1, nz))) * RAD2DEG;
  if (snap) {
    // Round both angles to nearest 90° so the clicked face ends up straight-on
    // with its text upright (no diagonal tilt from edge/corner clicks).
    az = Math.round(az / 90) * 90;
    el = Math.round(el / 90) * 90;
  }
  // Keep elevation off the poles to prevent gimbal lock in OrbitControls / lookAt.
  if (Math.abs(el) >= MAX_EL) {
    el = Math.sign(el) * MAX_EL;
    az = 0; // canonical orientation so top/bottom views always face the same way
  }
  return { azimuthDeg: az, elevationDeg: el, zoom: liveView.zoom };
}

export function NavCube({ onClickView }: Props) {
  const handleClick = (e: ThreeEvent<MouseEvent>): null => {
    e.stopPropagation();
    const snap = e.shiftKey;
    const pos = e.object.position;
    let view: ViewSettings;
    if (pos.length() < 0.01) {
      // Face click — face normal in box local space gives the world direction
      const n = e.face?.normal;
      if (!n) return null;
      view = directionToView(n.x, n.y, n.z, snap);
    } else {
      // Edge or corner — mesh center position is the direction vector
      view = directionToView(pos.x, pos.y, pos.z, snap);
    }
    onClickView(view);
    return null;
  };

  return (
    <GizmoHelper alignment="top-right" margin={[72, 72]}>
      <GizmoViewcube
        color="#f1f5f9"
        hoverColor="#93c5fd"
        textColor="#1e293b"
        strokeColor="#cbd5e1"
        opacity={0.92}
        faces={FACES}
        onClick={handleClick}
      />
    </GizmoHelper>
  );
}
