import { createContext, useContext, type ReactNode } from "react";

import { useAppStore } from "../store/useAppStore";
import { useMeshes, type MeshState } from "./useMeshes";

const MeshContext = createContext<MeshState>({ meshes: new Map(), ready: false, error: null });

/**
 * Loads the project meshes once and shares them with every viewport via
 * context, so the freeform and step-view canvases don't each re-read files.
 * (The same BufferGeometry can be used across multiple WebGL renderers.)
 */
export function MeshProvider({ children }: { children: ReactNode }) {
  const source = useAppStore((s) => s.source);
  const model = useAppStore((s) => s.model);
  const state = useMeshes(source, model);
  return <MeshContext.Provider value={state}>{children}</MeshContext.Provider>;
}

export function useMeshContext(): MeshState {
  return useContext(MeshContext);
}
