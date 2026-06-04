import { useEffect } from "react";
import { useThree } from "@react-three/fiber";
import * as THREE from "three";

interface OrbitLike {
  target: THREE.Vector3;
  update: () => void;
}

const MIN_ZOOM = 0.02;
const MAX_ZOOM = 5000;
const ZOOM_SENSITIVITY = 0.01;

function clamp(n: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, n));
}

/**
 * macOS-trackpad-friendly wheel handling for an orthographic camera, layered on
 * top of OrbitControls (which keeps drag-to-rotate). The browser surfaces both
 * trackpad gestures as `wheel` events:
 *
 *   - **pinch**         → `ctrlKey === true`  → zoom (toward the cursor)
 *   - **two-finger pan** → `ctrlKey === false` → pan
 *
 * OrbitControls' own wheel handler only ever dollies/zooms, which is why an
 * unmodified setup zooms when you try to two-finger pan. We disable its zoom
 * (`enableZoom={false}`) and drive both gestures here.
 *
 * R3F sizes the default orthographic frustum in pixels, so at `camera.zoom = z`
 * one screen pixel equals `1 / z` world units — which makes the pan and
 * zoom-to-cursor math exact.
 */
export function TrackpadControls(): null {
  const camera = useThree((s) => s.camera) as THREE.OrthographicCamera;
  const controls = useThree((s) => s.controls) as unknown as OrbitLike | null;
  const gl = useThree((s) => s.gl);
  const size = useThree((s) => s.size);
  const invalidate = useThree((s) => s.invalidate);

  useEffect(() => {
    // Listen on the canvas's wrapper (capture phase) so wheel events that land
    // on overlaid drei <Html> labels — siblings of the canvas — are still
    // intercepted and don't scroll the page.
    const el = gl.domElement.parentElement ?? gl.domElement;
    const rectEl = gl.domElement;
    const right = new THREE.Vector3();
    const up = new THREE.Vector3();

    const onWheel = (e: WheelEvent) => {
      // Always stop the page from scrolling / pinch-zooming the document.
      e.preventDefault();
      if (!controls) return;

      const target = controls.target;
      right.setFromMatrixColumn(camera.matrix, 0).normalize();
      up.setFromMatrixColumn(camera.matrix, 1).normalize();

      if (e.ctrlKey) {
        // Pinch → zoom toward the point under the cursor.
        const rect = rectEl.getBoundingClientRect();
        const px = e.clientX - rect.left - size.width / 2; // +right of center
        const py = e.clientY - rect.top - size.height / 2; // +down from center

        const oldZoom = camera.zoom;
        const newZoom = clamp(oldZoom * Math.exp(-e.deltaY * ZOOM_SENSITIVITY), MIN_ZOOM, MAX_ZOOM);
        if (newZoom === oldZoom) return;

        // Keep the cursor's world point fixed: screen +down maps to world -up.
        const f = 1 / oldZoom - 1 / newZoom;
        const shift = right
          .clone()
          .multiplyScalar(px * f)
          .add(up.clone().multiplyScalar(-py * f));
        camera.position.add(shift);
        target.add(shift);

        camera.zoom = newZoom;
        camera.updateProjectionMatrix();
      } else {
        // Two-finger scroll → pan (the scene follows the fingers, 1:1 on screen).
        const k = 1 / camera.zoom;
        const move = right
          .clone()
          .multiplyScalar(e.deltaX * k)
          .add(up.clone().multiplyScalar(-e.deltaY * k));
        camera.position.add(move);
        target.add(move);
      }

      controls.update();
      invalidate();
    };

    const opts: AddEventListenerOptions = { passive: false, capture: true };
    el.addEventListener("wheel", onWheel, opts);
    return () => el.removeEventListener("wheel", onWheel, opts);
  }, [camera, controls, gl, size.width, size.height, invalidate]);

  return null;
}
