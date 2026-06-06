import { useEffect, useMemo, useRef, useState } from "react";
import type { MouseEvent } from "react";

import { partColor } from "../lib/color";
import { selectedStep, useAppStore } from "../store/useAppStore";
import { resolveExisting } from "../types/manual";
import type { ModelInstance, ModelPart } from "../types/model";

export function PartsPanel() {
  const model = useAppStore((s) => s.model);
  const manual = useAppStore((s) => s.manual);
  const step = useAppStore(selectedStep);
  const selectedInstanceId = useAppStore((s) => s.selectedInstanceId);
  const selectedInstanceIds = useAppStore((s) => s.selectedInstanceIds);
  const selectInstance = useAppStore((s) => s.selectInstance);
  const setSelection = useAppStore((s) => s.setSelection);
  const toggleInstanceSelection = useAppStore((s) => s.toggleInstanceSelection);
  const hoverInstance = useAppStore((s) => s.hoverInstance);
  const setPartAdded = useAppStore((s) => s.setPartAdded);
  const setPartsAdded = useAppStore((s) => s.setPartsAdded);
  const [query, setQuery] = useState("");

  const selectedSet = useMemo(() => new Set(selectedInstanceIds), [selectedInstanceIds]);

  // Scroll the selected row into view when selection changes (e.g. from a 3D click).
  const selectedRowRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    selectedRowRef.current?.scrollIntoView({ block: "nearest" });
  }, [selectedInstanceId]);

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

  // Flattened display order, used to resolve Shift+click ranges.
  const orderedIds = groups.flatMap((g) => g.items.map((i) => i.id));

  // Selection-aware click: Shift = range from anchor, Cmd/Ctrl = toggle, else single.
  const handleRowClick = (e: MouseEvent, id: string) => {
    if (e.shiftKey && selectedInstanceId && orderedIds.includes(selectedInstanceId)) {
      const a = orderedIds.indexOf(selectedInstanceId);
      const b = orderedIds.indexOf(id);
      const [lo, hi] = a <= b ? [a, b] : [b, a];
      setSelection(orderedIds.slice(lo, hi + 1), selectedInstanceId);
    } else if (e.metaKey || e.ctrlKey) {
      toggleInstanceSelection(id);
    } else {
      selectInstance(id);
    }
  };

  // Bulk targets among the current selection (only meaningful with a step).
  const addable = step
    ? selectedInstanceIds.filter((id) => !existing.has(id) && !step.added.includes(id))
    : [];
  const removable = step ? selectedInstanceIds.filter((id) => step.added.includes(id)) : [];

  if (!model) return <div className="panel-empty">Open a project to browse parts.</div>;

  const renderRow = (inst: ModelInstance) => {
    const part = partsByKey.get(inst.partKey);
    const isAdded = step ? step.added.includes(inst.id) : false;
    const isExisting = existing.has(inst.id);
    const isAnchor = inst.id === selectedInstanceId;
    const isSelected = selectedSet.has(inst.id);
    return (
      <div
        key={inst.id}
        ref={isAnchor ? selectedRowRef : undefined}
        className={`part-row${isSelected ? " part-row--selected" : ""}`}
        onClick={(e) => handleRowClick(e, inst.id)}
        onMouseEnter={() => hoverInstance(inst.id)}
        onMouseLeave={() => hoverInstance(null)}
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

      {selectedInstanceIds.length > 1 ? (
        <div className="part-bulk-bar">
          <span className="part-bulk-count">{selectedInstanceIds.length} selected</span>
          {step && addable.length ? (
            <button className="chip chip--add" onClick={() => setPartsAdded(addable, true)}>
              + Add {addable.length}
            </button>
          ) : null}
          {step && removable.length ? (
            <button className="chip chip--added" onClick={() => setPartsAdded(removable, false)}>
              Remove {removable.length}
            </button>
          ) : null}
          <button className="chip" onClick={() => selectInstance(null)} title="Clear selection">
            Clear
          </button>
        </div>
      ) : null}

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
