import { useEffect, useState } from "react";
import type * as THREE from "three";

import { ProjectSource } from "../fs/projectSource";
import { buildGeometry } from "../lib/geometry";
import type { MeshData, ModelData } from "../types/model";

export interface PartGeometry {
  mesh: MeshData;
  geometry: THREE.BufferGeometry;
}

export interface MeshState {
  meshes: Map<string, PartGeometry>;
  ready: boolean;
  error: string | null;
}

/**
 * Loads every part mesh referenced by the model through the project source and
 * builds GPU geometries. Re-runs when the model changes and disposes the
 * previous geometries to avoid leaks.
 */
export function useMeshes(source: ProjectSource | null, model: ModelData | null): MeshState {
  const [state, setState] = useState<MeshState>({
    meshes: new Map(),
    ready: false,
    error: null,
  });

  useEffect(() => {
    if (!source || !model) {
      setState({ meshes: new Map(), ready: false, error: null });
      return;
    }
    let cancelled = false;
    const loaded = new Map<string, PartGeometry>();
    setState({ meshes: new Map(), ready: false, error: null });

    (async () => {
      try {
        for (const part of model.parts) {
          const mesh = await source.readMesh(part.mesh);
          loaded.set(part.key, { mesh, geometry: buildGeometry(mesh) });
        }
        if (cancelled) {
          loaded.forEach((p) => p.geometry.dispose());
          return;
        }
        setState({ meshes: loaded, ready: true, error: null });
      } catch (err) {
        if (!cancelled) {
          setState({ meshes: new Map(), ready: false, error: errorMessage(err) });
        }
      }
    })();

    return () => {
      cancelled = true;
      loaded.forEach((p) => p.geometry.dispose());
    };
  }, [source, model]);

  return state;
}

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}
