import { isFileSystemAccessSupported } from "../fs/pick";
import { useAppStore } from "../store/useAppStore";

/** Landing / connection screen shown whenever no project is open. */
export function ProjectGate() {
  const status = useAppStore((s) => s.status);
  const error = useAppStore((s) => s.error);
  const reconnectHandle = useAppStore((s) => s.reconnectHandle);
  const subprojectChoice = useAppStore((s) => s.subprojectChoice);
  const projectName = useAppStore((s) => s.projectName);
  const pickAndOpen = useAppStore((s) => s.pickAndOpen);
  const reconnect = useAppStore((s) => s.reconnect);
  const openSubproject = useAppStore((s) => s.openSubproject);

  const supported = isFileSystemAccessSupported();

  return (
    <div className="gate">
      <div className="gate-card">
        <h1>Manual Builder</h1>
        <p className="gate-lead">
          Author step-by-step assembly manuals for papercut models. Open a project directory
          (one of <code>projects/*</code>) — its <code>manual/</code> folder is read and written
          directly in your browser.
        </p>

        {!supported ? (
          <p className="gate-error">
            This browser does not support the File System Access API. Please use Chrome or Edge.
          </p>
        ) : reconnectHandle ? (
          <>
            <p>
              Reconnect to <strong>{projectName}</strong> to restore your session.
            </p>
            <button className="btn btn--primary btn--lg" onClick={reconnect}>
              Reconnect to {projectName}
            </button>
            <button className="btn btn--ghost" onClick={pickAndOpen}>
              Open a different project
            </button>
          </>
        ) : subprojectChoice ? (
          <>
            <p>Choose a project from this folder:</p>
            <div className="gate-projects">
              {subprojectChoice.names.map((name) => (
                <button key={name} className="btn btn--lg" onClick={() => openSubproject(name)}>
                  {name}
                </button>
              ))}
            </div>
          </>
        ) : (
          <button
            className="btn btn--primary btn--lg"
            onClick={pickAndOpen}
            disabled={status === "loading"}
          >
            {status === "loading" ? "Opening…" : "Open project directory"}
          </button>
        )}

        {error ? <p className="gate-error">{error}</p> : null}

        <p className="gate-note">
          Need model data first? Run <code>./process &lt;project&gt;</code> (or
          <code> export_manual.py</code>) to generate <code>manual/model/</code>.
        </p>
      </div>
    </div>
  );
}
