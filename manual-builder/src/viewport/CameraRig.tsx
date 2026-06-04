import { useCallback, useEffect, useRef } from "react";
import { useThree } from "@react-three/fiber";
import type * as THREE from "three";

import { cameraPose, viewFromCamera } from "../lib/camera";
import { upVector } from "../lib/vec";
import type { UpAxis, ViewSettings } from "../types/manual";
import type { Vec3 } from "../types/model";
import { liveView } from "./liveView";

interface OrbitLike {
  target: THREE.Vector3;
  update: () => void;
  addEventListener: (type: string, cb: () => void) => void;
  removeEventListener: (type: string, cb: () => void) => void;
}

interface Props {
  view: ViewSettings;
  upAxis: UpAxis;
  target: Vec3;
  radius: number;
  /**
   * `false` (follow): the camera tracks `view` continuously — used by the
   * persistent step-view preview.
   * `true` (free): the camera is user-controlled and only snaps to `view` when
   * `applyKey` changes — used by the freeform viewport. While free, the camera's
   * orientation is mirrored into `liveView` for "save as step view".
   */
  interactive: boolean;
  /** Bump to force a free camera to re-apply `view`. */
  applyKey?: number;
}

export function CameraRig({ view, upAxis, target, radius, interactive, applyKey = 0 }: Props): null {
  const camera = useThree((s) => s.camera) as THREE.OrthographicCamera;
  const controls = useThree((s) => s.controls) as unknown as OrbitLike | null;
  const size = useThree((s) => s.size);
  const invalidate = useThree((s) => s.invalidate);

  const distance = Math.max(radius * 4, 1);
  const fitZoom = (Math.min(size.width, size.height) / (2 * Math.max(radius, 1e-3))) * 0.85;

  // Latest framing kept in a ref so imperative applies read current values
  // without forcing the free camera to re-apply on every prop change.
  const latest = useRef({ view, upAxis, target, distance, fitZoom });
  latest.current = { view, upAxis, target, distance, fitZoom };

  const applyView = useCallback(() => {
    const cur = latest.current;
    const pose = cameraPose(cur.view, cur.upAxis, cur.target, cur.distance);
    const up = upVector(cur.upAxis);
    camera.up.set(up[0], up[1], up[2]);
    camera.position.set(pose.position[0], pose.position[1], pose.position[2]);
    camera.near = 0.01;
    camera.far = cur.distance * 8;
    camera.zoom = cur.fitZoom * cur.view.zoom;
    camera.updateProjectionMatrix();
    if (controls) {
      controls.target.set(cur.target[0], cur.target[1], cur.target[2]);
      controls.update();
    } else {
      camera.lookAt(cur.target[0], cur.target[1], cur.target[2]);
    }
    invalidate();
  }, [camera, controls, invalidate]);

  // Follow mode: re-apply whenever the view or framing changes.
  useEffect(() => {
    if (interactive) return;
    applyView();
  }, [
    interactive,
    applyView,
    view.azimuthDeg,
    view.elevationDeg,
    view.zoom,
    upAxis,
    target[0],
    target[1],
    target[2],
    distance,
    fitZoom,
  ]);

  // Free mode: apply only on explicit token change (and once controls are ready).
  useEffect(() => {
    if (!interactive) return;
    applyView();
  }, [interactive, applyView, applyKey]);

  // Free mode: mirror the orbiting camera into liveView for "save as step view".
  useEffect(() => {
    if (!interactive || !controls) return;
    const handler = () => {
      const captured = viewFromCamera(
        [camera.position.x, camera.position.y, camera.position.z],
        [controls.target.x, controls.target.y, controls.target.z],
        latest.current.upAxis,
        camera.zoom / Math.max(latest.current.fitZoom, 1e-6),
      );
      liveView.azimuthDeg = captured.azimuthDeg;
      liveView.elevationDeg = captured.elevationDeg;
      liveView.zoom = captured.zoom;
    };
    controls.addEventListener("change", handler);
    handler();
    return () => controls.removeEventListener("change", handler);
  }, [interactive, camera, controls]);

  return null;
}
