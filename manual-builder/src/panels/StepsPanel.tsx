import { useState } from "react";

import { useAppStore } from "../store/useAppStore";
import { isRepeated, repeatCount, resolveExisting } from "../types/manual";

export function StepsPanel() {
  const manual = useAppStore((s) => s.manual);
  const selectedStepId = useAppStore((s) => s.selectedStepId);
  const addStep = useAppStore((s) => s.addStep);
  const addIndependentStep = useAppStore((s) => s.addIndependentStep);
  const selectStep = useAppStore((s) => s.selectStep);
  const deleteStep = useAppStore((s) => s.deleteStep);
  const moveStep = useAppStore((s) => s.moveStep);
  const removeRepeatCopy = useAppStore((s) => s.removeRepeatCopy);

  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const toggleExpanded = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  if (!manual) {
    return <div className="panel-empty">Open a project to author steps.</div>;
  }
  const steps = manual.steps;

  return (
    <div className="panel panel--steps">
      <div className="panel-header">
        <span>Steps</span>
        <span className="step-add-actions">
          <button
            className="btn btn--small"
            onClick={addIndependentStep}
            title="New independent step (no dependencies — starts from scratch)"
          >
            + Independent
          </button>
          <button
            className="btn btn--primary btn--small"
            onClick={addStep}
            title="New step that depends on the selected step"
          >
            + Add
          </button>
        </span>
      </div>

      {steps.length === 0 ? (
        <div className="panel-empty">No steps yet. Add the first one.</div>
      ) : (
        <ol className="step-list">
          {steps.map((step, index) => {
            const repeated = isRepeated(step);
            const isOpen = expanded.has(step.id);
            return (
              <li key={step.id} className="step-li">
                <div
                  className={`step-item${step.id === selectedStepId ? " step-item--active" : ""}`}
                  onClick={() => selectStep(step.id)}
                >
                  {repeated ? (
                    <button
                      className="btn btn--icon step-expand"
                      title={isOpen ? "Collapse copies" : "Show copies"}
                      onClick={(e) => {
                        e.stopPropagation();
                        toggleExpanded(step.id);
                      }}
                    >
                      {isOpen ? "▾" : "▸"}
                    </button>
                  ) : (
                    <span className="step-expand-spacer" />
                  )}
                  <span className="step-index">{index + 1}</span>
                  <span className="step-body">
                    <span className="step-title">
                      {step.description.trim() || `Step ${index + 1}`}
                      {repeated ? <span className="repeat-badge">×{repeatCount(step)}</span> : null}
                    </span>
                    <span className="step-meta">
                      {resolveExisting(manual, step).size} existing · {step.added.length} new
                      {repeated ? ` · repeated` : ""}
                    </span>
                  </span>
                  <span className="step-actions" onClick={(e) => e.stopPropagation()}>
                    <button
                      className="btn btn--icon"
                      title="Move up"
                      disabled={index === 0}
                      onClick={() => moveStep(step.id, -1)}
                    >
                      ↑
                    </button>
                    <button
                      className="btn btn--icon"
                      title="Move down"
                      disabled={index === steps.length - 1}
                      onClick={() => moveStep(step.id, 1)}
                    >
                      ↓
                    </button>
                    <button
                      className="btn btn--icon btn--danger"
                      title="Delete step"
                      onClick={() => deleteStep(step.id)}
                    >
                      ✕
                    </button>
                  </span>
                </div>

                {repeated && isOpen ? (
                  <ul className="step-copy-list">
                    <li className="step-copy-row">
                      <span className="step-copy-label">Primary (template)</span>
                    </li>
                    {step.repeat!.copies.map((copy, i) => (
                      <li key={copy.id} className="step-copy-row">
                        <span className="step-copy-label">Copy {i + 2}</span>
                        <button
                          className="btn btn--icon btn--danger"
                          title="Remove this copy"
                          onClick={() => {
                            // removeRepeatCopy targets the selected step.
                            selectStep(step.id);
                            removeRepeatCopy(copy.id);
                          }}
                        >
                          ✕
                        </button>
                      </li>
                    ))}
                  </ul>
                ) : null}
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
