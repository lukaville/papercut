import { useAppStore, type SaveState } from "../store/useAppStore";

const SAVE_LABEL: Record<SaveState, string> = {
  idle: "",
  saving: "Saving…",
  saved: "Saved",
  error: "Save failed",
};

export function Toolbar({ onResetLayout }: { onResetLayout: () => void }) {
  const projectName = useAppStore((s) => s.projectName);
  const status = useAppStore((s) => s.status);
  const saveState = useAppStore((s) => s.saveState);
  const pickAndOpen = useAppStore((s) => s.pickAndOpen);
  const closeProject = useAppStore((s) => s.closeProject);
  const reloadModel = useAppStore((s) => s.reloadModel);

  const isOpen = status === "ready";

  return (
    <header className="toolbar">
      <div className="toolbar-brand">
        Papercut <span className="toolbar-sub">Manual Builder</span>
      </div>
      <div className="toolbar-spacer" />
      {isOpen ? (
        <>
          <span className={`save-state save-state--${saveState}`}>{SAVE_LABEL[saveState]}</span>
          <span className="toolbar-project">{projectName}</span>
          <button className="btn" onClick={reloadModel} title="Re-read model.json from disk">
            Reload model
          </button>
          <button className="btn" onClick={onResetLayout} title="Reset panels to the default layout">
            Reset layout
          </button>
          <button className="btn" onClick={pickAndOpen}>
            Open…
          </button>
          <button className="btn btn--ghost" onClick={closeProject}>
            Close
          </button>
        </>
      ) : (
        <button className="btn btn--primary" onClick={pickAndOpen}>
          Open project…
        </button>
      )}
    </header>
  );
}
