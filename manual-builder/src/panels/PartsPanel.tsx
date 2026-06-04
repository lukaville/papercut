import { useMemo, useState } from "react";

import { partColor } from "../lib/color";
import { selectedStep, useAppStore } from "../store/useAppStore";
import { resolveExisting } from "../types/manual";
import type { ModelInstance, ModelPart } from "../types/model";

export function PartsPanel() {
  const model = useAppStore((s) => s.model);
  const manual = useAppStore((s) => s.manual);
  const step = useAppStore(selectedStep);
  const selectedInstanceId = useAppStore((s) => s.selectedInstanceId);
  const selectInstance = useAppStore((s) => s.selectInstance);
  const setPartAdded = useAppStore((s) => s.setPartAdded);
  const [query, setQuery] = useState("");

  const partsByKey = useMemo(() => {
    const map = new Map<string, ModelPart>();
    for (const part of model?.parts ?? []) map.set(part.key, part);
    return map;
  }, [model]);

  // Filtered + naturally sorted instances.
  const instances = useMemo(() => {
    const list = model?.instances ?? [];
    const q = query.trim().toLowerCase();
    const filtered = q
      ? list.filter(
          (i) =>
            i.id.toLowerCase().includes(q) ||
            i.partKey.toLowerCase().includes(q) ||
            (i.sheet ?? "").toLowerCase().includes(q),
        )
      : list;
    return [...filtered].sort((a, b) =>
      (a.sheet ?? a.id).localeCompare(b.sheet ?? b.id, undefined, { numeric: true }),
    );
  }, [model, query]);

  // Existing context is derived from the step's dependencies.
  const existing = useMemo(
    () => (manual && step ? resolveExisting(manual, step) : new Set<string>()),
    [manual, step],
  );

  // Group: new in step, existing context, then everything else.
  const groups = useMemo(() => {
    if (!step) return [{ label: "All parts", items: instances }];
    const added = new Set(step.added);
    return [
      { label: "New in step", items: instances.filter((i) => added.has(i.id)) },
      {
        label: "Existing (context)",
        items: instances.filter((i) => !added.has(i.id) && existing.has(i.id)),
      },
      {
        label: "Other parts",
        items: instances.filter((i) => !added.has(i.id) && !existing.has(i.id)),
      },
    ];
  }, [instances, step, existing]);

  if (!model) return <div className="panel-empty">Open a project to browse parts.</div>;

  const renderRow = (inst: ModelInstance) => {
    const part = partsByKey.get(inst.partKey);
    const isAdded = step ? step.added.includes(inst.id) : false;
    const isExisting = existing.has(inst.id);
    return (
      <div
        key={inst.id}
        className={`part-row${inst.id === selectedInstanceId ? " part-row--selected" : ""}`}
        onClick={() => selectInstance(inst.id)}
      >
        <span className="swatch" style={{ background: part ? partColor(part.color) : "#ccc" }} />
        <span className="part-row-main">
          <span className="part-sheet">{inst.sheet ?? "—"}</span>
          <span className="part-id">{inst.id}</span>
        </span>
        <span className="part-row-actions" onClick={(e) => e.stopPropagation()}>
          {isAdded ? (
            <button
              className="chip chip--added"
              onClick={() => setPartAdded(inst.id, false)}
              title="Remove from this step"
            >
              new ✕
            </button>
          ) : isExisting ? (
            <span className="chip chip--built" title="Existing context (from dependencies)">
              existing
            </span>
          ) : (
            <button
              className="chip chip--add"
              disabled={!step}
              onClick={() => setPartAdded(inst.id, true)}
              title="Add as new in this step"
            >
              + new
            </button>
          )}
        </span>
      </div>
    );
  };

  return (
    <div className="panel panel--parts">
      <div className="panel-header">
        <span>Parts ({model.instances.length})</span>
      </div>
      <input
        className="input"
        placeholder="Filter by sheet, id or name…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      {!step ? <div className="hint">Select a step to assign parts to it.</div> : null}

      <div className="part-scroll">
        {groups.map((group) =>
          group.items.length ? (
            <div key={group.label}>
              <div className="part-group-header">
                {group.label} · {group.items.length}
              </div>
              {group.items.map(renderRow)}
            </div>
          ) : null,
        )}
      </div>
    </div>
  );
}
