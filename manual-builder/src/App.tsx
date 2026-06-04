import { useCallback, useEffect, useState } from "react";

import { ProjectGate } from "./components/ProjectGate";
import { Toolbar } from "./components/Toolbar";
import { Layout } from "./layout/Layout";
import { clearSavedLayout } from "./layout/layoutStorage";
import { useAppStore } from "./store/useAppStore";
import { MeshProvider } from "./viewport/MeshProvider";

export function App() {
  const status = useAppStore((s) => s.status);
  const model = useAppStore((s) => s.model);
  const restoreSession = useAppStore((s) => s.restoreSession);

  // Bumping this key remounts the Layout, recreating its FlexLayout model.
  const [layoutKey, setLayoutKey] = useState(0);
  const resetLayout = useCallback(() => {
    clearSavedLayout();
    setLayoutKey((k) => k + 1);
  }, []);

  useEffect(() => {
    void restoreSession();
  }, [restoreSession]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!e.metaKey && !e.ctrlKey) return;
      if (e.key === "z" && !e.shiftKey) {
        e.preventDefault();
        useAppStore.getState().undo();
      } else if (e.key === "y" || (e.key === "z" && e.shiftKey)) {
        e.preventDefault();
        useAppStore.getState().redo();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const ready = status === "ready" && model !== null;

  return (
    <div className="app">
      <Toolbar onResetLayout={resetLayout} />
      {ready ? (
        <MeshProvider>
          <Layout key={layoutKey} />
        </MeshProvider>
      ) : (
        <ProjectGate />
      )}
    </div>
  );
}
