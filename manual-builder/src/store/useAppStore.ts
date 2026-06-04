import { create } from "zustand";
import { persist } from "zustand/middleware";

import { ProjectSource } from "../fs/projectSource";
import { captureLiveView } from "../viewport/liveView";
import {
  clearProjectHandle,
  loadProjectHandle,
  saveProjectHandle,
} from "../fs/handleStore";
import {
  ensurePermission,
  isProjectDir,
  listProjectSubdirs,
  pickDirectory,
} from "../fs/pick";
import type { ModelData } from "../types/model";
import {
  allAddedInstanceIds,
  normalizeManual,
  repeatCopyInstanceIds,
  subassemblyGroup,
  templateInstanceFor,
  wouldCreateCycle,
} from "../types/manual";
import { detectRepeats } from "../lib/repeat";
import type {
  Connection,
  ExplodeSettings,
  ManualDefaults,
  ManualDocument,
  Step,
  VertexRef,
  ViewSettings,
} from "../types/manual";

export type Status = "idle" | "loading" | "ready" | "error";
export type SaveState = "idle" | "saving" | "saved" | "error";

export interface UiFlags {
  /** Vertex-connection authoring mode. */
  connectMode: boolean;
  /** Render clickable handles at topological vertices. */
  showVertices: boolean;
  /** Render already-built parts (ghosted). */
  showCompleted: boolean;
  /** Render sheet-label badges over parts. */
  showLabels: boolean;
  /** Render the world origin axes (X/Y/Z) and center marker. */
  showOrigin: boolean;
  /** Show every copy of a repeated step (preview), not just the primary. */
  previewRepeats: boolean;
}

interface SubprojectChoice {
  root: FileSystemDirectoryHandle;
  names: string[];
}

interface AppState {
  // --- session data (not persisted) ---
  source: ProjectSource | null;
  model: ModelData | null;
  manual: ManualDocument | null;
  status: Status;
  error: string | null;
  saveState: SaveState;
  /** A stored handle whose permission must be re-granted by a user gesture. */
  reconnectHandle: FileSystemDirectoryHandle | null;
  /** Set when a picked directory contains multiple projects to choose from. */
  subprojectChoice: SubprojectChoice | null;
  /** Bumped to make the freeform viewport snap back to the step view. */
  freeformApplyToken: number;
  /** Undo/redo history stacks (not persisted). */
  undoStack: ManualDocument[];
  redoStack: ManualDocument[];
  /** Explode preview scale: 0 = assembled, 1 = full explode. Not persisted. */
  explodeScale: number;

  // --- persisted UI state ---
  projectName: string | null;
  selectedStepId: string | null;
  /** The instance focused by the part inspector (within the selected step). */
  selectedInstanceId: string | null;
  pendingVertex: VertexRef | null;
  ui: UiFlags;

  // --- lifecycle ---
  restoreSession: () => Promise<void>;
  pickAndOpen: () => Promise<void>;
  openSubproject: (name: string) => Promise<void>;
  reconnect: () => Promise<void>;
  closeProject: () => Promise<void>;
  reloadModel: () => Promise<void>;

  // --- document mutations ---
  setTitle: (title: string) => void;
  updateDefaults: (patch: Partial<ManualDefaults>) => void;
  /** Append a step depending on the current/last step (default flow). */
  addStep: () => void;
  /** Append an independent step (no dependencies — starts from scratch). */
  addIndependentStep: () => void;
  deleteStep: (id: string) => void;
  updateStep: (id: string, patch: Partial<Omit<Step, "id">>) => void;
  moveStep: (id: string, dir: -1 | 1) => void;
  selectStep: (id: string | null) => void;
  selectInstance: (instanceId: string | null) => void;
  /** Toggle a dependency (by step id) on the selected step. */
  toggleStepDependency: (depId: string) => void;
  /** Add/remove an instance from the selected step's `added` (new) parts. */
  setPartAdded: (instanceId: string, added: boolean) => void;
  setStepView: (view: ViewSettings | null) => void;
  /** Save the freeform viewport's current camera as the selected step's view. */
  saveFreeformView: () => void;
  /** Snap the freeform viewport back to the selected step's view. */
  resetFreeformView: () => void;
  /** Transient view set by the NavCube; overrides the step view until the user orbits. */
  transientFreeformView: ViewSettings | null;
  /** Jump the freeform viewport to a preset orientation (e.g. from NavCube). */
  applyFreeformView: (view: ViewSettings) => void;
  /** Set or clear (null) the per-part explode override for one instance. */
  setPartExplode: (instanceId: string, explode: ExplodeSettings | null) => void;
  /** Auto-detect repeated copies of the selected step's new parts. */
  detectStepRepeats: () => void;
  /** Drop all repeat copies from the selected step. */
  clearStepRepeat: () => void;
  /** Remove one detected repeat copy from the selected step. */
  removeRepeatCopy: (copyId: string) => void;
  addConnection: (from: VertexRef, toPart: string) => void;
  removeConnection: (connectionId: string) => void;
  clearConnections: () => void;
  hoveredConnectionId: string | null;
  setHoveredConnection: (id: string | null) => void;

  setExplodeScale: (scale: number) => void;

  // --- history ---
  undo: () => void;
  redo: () => void;

  // --- ui ---
  setUi: (patch: Partial<UiFlags>) => void;
  /** In connect mode: stage a source vertex; second step is clicking the target part. */
  pickVertex: (ref: VertexRef) => void;
  clearPendingVertex: () => void;
}

let saveTimer: ReturnType<typeof setTimeout> | null = null;

export const useAppStore = create<AppState>()(
  persist(
    (set, get) => {
      /** Persist the current manual to disk, debounced. */
      const scheduleSave = () => {
        if (saveTimer) clearTimeout(saveTimer);
        set({ saveState: "saving" });
        saveTimer = setTimeout(async () => {
          const { source, manual } = get();
          if (!source || !manual) return;
          try {
            await source.writeManual(manual);
            set({ saveState: "saved" });
          } catch (err) {
            set({ saveState: "error", error: errorMessage(err) });
          }
        }, 600);
      };

      const HISTORY_LIMIT = 100;

      /** Apply an immutable mutation to the manual and schedule a save. */
      const mutate = (fn: (doc: ManualDocument) => void) => {
        const current = get().manual;
        if (!current) return;
        const next = structuredClone(current) as ManualDocument;
        fn(next);
        const prev = get().undoStack;
        set({
          manual: next,
          undoStack: [...prev, current].slice(-HISTORY_LIMIT),
          redoStack: [],
        });
        scheduleSave();
      };

      const updateStepBy = (id: string, fn: (step: Step) => void) =>
        mutate((doc) => {
          const step = doc.steps.find((s) => s.id === id);
          if (step) fn(step);
        });

      const withSelectedStep = (fn: (step: Step) => void) => {
        const id = get().selectedStepId;
        if (id) updateStepBy(id, fn);
      };

      const openFromHandle = async (
        handle: FileSystemDirectoryHandle,
        interactive: boolean,
      ) => {
        const permission = await ensurePermission(handle, interactive);
        if (permission !== "granted") {
          set({ reconnectHandle: handle, status: "idle", projectName: handle.name });
          return;
        }
        set({ status: "loading", error: null, reconnectHandle: null, subprojectChoice: null });
        try {
          const source = new ProjectSource(handle);
          const [model, rawManual] = await Promise.all([source.readModel(), source.readManual()]);
          const manual = normalizeManual(rawManual);
          await saveProjectHandle(handle);
          const selectedStepId = resolveSelectedStep(manual, get().selectedStepId);
          set({
            source,
            model,
            manual,
            projectName: source.name,
            status: "ready",
            saveState: "idle",
            selectedStepId,
            selectedInstanceId: null,
            pendingVertex: null,
            transientFreeformView: null,
            undoStack: [],
            redoStack: [],
          });
        } catch (err) {
          set({ status: "error", error: errorMessage(err) });
        }
      };

      return {
        source: null,
        model: null,
        manual: null,
        status: "idle",
        error: null,
        saveState: "idle",
        reconnectHandle: null,
        subprojectChoice: null,
        freeformApplyToken: 0,
        transientFreeformView: null,
        undoStack: [],
        redoStack: [],
        explodeScale: 1,

        projectName: null,
        selectedStepId: null,
        selectedInstanceId: null,
        pendingVertex: null,
        hoveredConnectionId: null,
        ui: {
          connectMode: false,
          showVertices: false,
          showCompleted: true,
          showLabels: true,
          showOrigin: true,
          previewRepeats: false,
        },

        restoreSession: async () => {
          const handle = await loadProjectHandle();
          if (!handle) return;
          await openFromHandle(handle, false);
        },

        pickAndOpen: async () => {
          let handle: FileSystemDirectoryHandle | null;
          try {
            handle = await pickDirectory();
          } catch (err) {
            set({ status: "error", error: errorMessage(err) });
            return;
          }
          if (!handle) return;

          if (await isProjectDir(handle)) {
            await openFromHandle(handle, true);
            return;
          }
          const names = await listProjectSubdirs(handle);
          if (names.length === 0) {
            set({
              status: "error",
              error: "That folder is not a papercut project and has no project subfolders.",
            });
            return;
          }
          if (names.length === 1) {
            const child = await handle.getDirectoryHandle(names[0]);
            await openFromHandle(child, true);
            return;
          }
          set({ subprojectChoice: { root: handle, names } });
        },

        openSubproject: async (name) => {
          const choice = get().subprojectChoice;
          if (!choice) return;
          const child = await choice.root.getDirectoryHandle(name);
          await openFromHandle(child, true);
        },

        reconnect: async () => {
          const handle = get().reconnectHandle;
          if (handle) await openFromHandle(handle, true);
        },

        closeProject: async () => {
          await clearProjectHandle();
          set({
            source: null,
            model: null,
            manual: null,
            projectName: null,
            status: "idle",
            error: null,
            selectedStepId: null,
            selectedInstanceId: null,
            pendingVertex: null,
            reconnectHandle: null,
            subprojectChoice: null,
            undoStack: [],
            redoStack: [],
          });
        },

        reloadModel: async () => {
          const source = get().source;
          if (!source) return;
          try {
            const model = await source.readModel();
            set({ model });
          } catch (err) {
            set({ status: "error", error: errorMessage(err) });
          }
        },

        setTitle: (title) => mutate((doc) => void (doc.title = title)),

        updateDefaults: (patch) =>
          mutate((doc) => {
            doc.defaults = { ...doc.defaults, ...patch };
          }),

        addStep: () => {
          const doc = get().manual;
          if (!doc) return;
          const id = crypto.randomUUID();
          const selId = get().selectedStepId;
          mutate((d) => {
            let baseIdx = selId ? d.steps.findIndex((s) => s.id === selId) : -1;
            if (baseIdx < 0) baseIdx = d.steps.length - 1;
            const base = baseIdx >= 0 ? d.steps[baseIdx] : null;
            d.steps.push({ ...newStep(id), dependsOn: base ? [base.id] : [] });
          });
          set({ selectedStepId: id, selectedInstanceId: null });
        },

        addIndependentStep: () => {
          const doc = get().manual;
          if (!doc) return;
          const id = crypto.randomUUID();
          mutate((d) => {
            d.steps.push(newStep(id)); // dependsOn defaults to []
          });
          set({ selectedStepId: id, selectedInstanceId: null });
        },

        deleteStep: (id) => {
          mutate((doc) => {
            doc.steps = doc.steps.filter((s) => s.id !== id);
            // Drop the deleted step from any remaining dependency lists.
            for (const s of doc.steps) {
              s.dependsOn = s.dependsOn.filter((d) => d !== id);
            }
          });
          if (get().selectedStepId === id) {
            const steps = get().manual?.steps ?? [];
            set({ selectedStepId: steps[0]?.id ?? null });
          }
        },

        updateStep: (id, patch) => updateStepBy(id, (step) => Object.assign(step, patch)),

        moveStep: (id, dir) =>
          mutate((doc) => {
            const i = doc.steps.findIndex((s) => s.id === id);
            const j = i + dir;
            if (i < 0 || j < 0 || j >= doc.steps.length) return;
            [doc.steps[i], doc.steps[j]] = [doc.steps[j], doc.steps[i]];
          }),

        selectStep: (id) =>
          set({ selectedStepId: id, selectedInstanceId: null, pendingVertex: null }),

        selectInstance: (instanceId) => set({ selectedInstanceId: instanceId }),

        toggleStepDependency: (depId) => {
          const doc = get().manual;
          const stepId = get().selectedStepId;
          if (!doc || !stepId || depId === stepId) return;
          withSelectedStep((step) => {
            if (step.dependsOn.includes(depId)) {
              step.dependsOn = step.dependsOn.filter((d) => d !== depId);
            } else if (!wouldCreateCycle(doc, stepId, depId)) {
              step.dependsOn.push(depId);
            }
          });
        },

        setPartAdded: (instanceId, added) =>
          withSelectedStep((step) => {
            step.added = step.added.filter((x) => x !== instanceId);
            if (added) step.added.push(instanceId);
            // Explode only applies to new parts; drop it when removed.
            if (!added && step.parts?.[instanceId]) {
              delete step.parts[instanceId];
              if (Object.keys(step.parts).length === 0) delete step.parts;
            }
          }),

        setStepView: (view) => withSelectedStep((step) => void (step.view = view)),

        saveFreeformView: () => get().setStepView(captureLiveView()),

        resetFreeformView: () =>
          set((s) => ({ freeformApplyToken: s.freeformApplyToken + 1, transientFreeformView: null })),

        applyFreeformView: (view) =>
          set((s) => ({ transientFreeformView: view, freeformApplyToken: s.freeformApplyToken + 1 })),

        setPartExplode: (instanceId, explode) =>
          withSelectedStep((step) => {
            const doc = get().manual!;
            // If a repeat copy of the CURRENT step is selected, redirect to its
            // template so the setting mirrors to every copy at render time.
            const target = templateInstanceFor(step, instanceId) ?? instanceId;
            const group = subassemblyGroup(doc, step, target);
            // Only skip instances that are repeat copies of the current step —
            // those are mirrored from the template at render time, not stored.
            // Context parts from dependency steps (including repeated ones) are
            // stored per-instance and must be written normally.
            const currentCopyIds = new Set(repeatCopyInstanceIds(step));
            for (const id of group) {
              if (currentCopyIds.has(id)) continue;
              if (explode === null) {
                if (step.parts?.[id]) delete step.parts[id];
              } else {
                step.parts ??= {};
                step.parts[id] = { ...step.parts[id], explode };
              }
            }
            if (step.parts && Object.keys(step.parts).length === 0) delete step.parts;
          }),

        detectStepRepeats: () => {
          const model = get().model;
          const doc = get().manual;
          const stepId = get().selectedStepId;
          if (!model || !doc || !stepId) return;
          const step = doc.steps.find((s) => s.id === stepId);
          if (!step || step.added.length === 0) return;
          // Never match instances already consumed by other steps.
          const exclude = new Set<string>();
          for (const s of doc.steps) {
            if (s.id === stepId) continue;
            for (const id of allAddedInstanceIds(s)) exclude.add(id);
          }
          const copies = detectRepeats(model, step.added, exclude);
          updateStepBy(stepId, (s) => {
            s.repeat = copies.length > 0 ? { copies } : null;
          });
          // Reveal the detected copies so the user can verify them at a glance.
          if (copies.length > 0) {
            set((s) => ({ ui: { ...s.ui, previewRepeats: true } }));
          }
        },

        clearStepRepeat: () =>
          withSelectedStep((step) => {
            step.repeat = null;
          }),

        removeRepeatCopy: (copyId) =>
          withSelectedStep((step) => {
            if (!step.repeat) return;
            step.repeat.copies = step.repeat.copies.filter((c) => c.id !== copyId);
            if (step.repeat.copies.length === 0) step.repeat = null;
          }),

        addConnection: (from, toPart) =>
          withSelectedStep((step) => {
            step.connections.push({ id: crypto.randomUUID(), from, toPart });
          }),

        removeConnection: (connectionId) =>
          withSelectedStep((step) => {
            step.connections = step.connections.filter((c) => c.id !== connectionId);
          }),

        clearConnections: () =>
          withSelectedStep((step) => {
            step.connections = [];
          }),

        setHoveredConnection: (id) => set({ hoveredConnectionId: id }),

        setExplodeScale: (scale) => set({ explodeScale: scale }),

        setUi: (patch) => set((state) => ({ ui: { ...state.ui, ...patch } })),

        pickVertex: (ref) => {
          const pending = get().pendingVertex;
          if (!pending) {
            set({ pendingVertex: ref });
          } else if (pending.instance === ref.instance && pending.vertex === ref.vertex) {
            set({ pendingVertex: null }); // toggle off
          } else {
            set({ pendingVertex: ref }); // switch to a different source vertex
          }
        },

        clearPendingVertex: () => set({ pendingVertex: null }),

        undo: () => {
          const { manual, undoStack, redoStack, selectedStepId } = get();
          if (!manual || undoStack.length === 0) return;
          const previous = undoStack[undoStack.length - 1];
          set({
            manual: previous,
            undoStack: undoStack.slice(0, -1),
            redoStack: [manual, ...redoStack],
            selectedStepId: resolveSelectedStep(previous, selectedStepId),
            selectedInstanceId: null,
            pendingVertex: null,
          });
          scheduleSave();
        },

        redo: () => {
          const { manual, undoStack, redoStack, selectedStepId } = get();
          if (!manual || redoStack.length === 0) return;
          const next = redoStack[0];
          set({
            manual: next,
            undoStack: [...undoStack, manual],
            redoStack: redoStack.slice(1),
            selectedStepId: resolveSelectedStep(next, selectedStepId),
            selectedInstanceId: null,
            pendingVertex: null,
          });
          scheduleSave();
        },
      };
    },
    {
      name: "papercut-manual-builder",
      partialize: (state) => ({
        projectName: state.projectName,
        selectedStepId: state.selectedStepId,
        selectedInstanceId: state.selectedInstanceId,
        ui: state.ui,
      }),
      // Deep-merge `ui` so flags added in newer versions keep their defaults
      // instead of being dropped by an older persisted snapshot.
      merge: (persisted, current) => {
        const p = (persisted ?? {}) as Partial<AppState>;
        return { ...current, ...p, ui: { ...current.ui, ...(p.ui ?? {}) } };
      },
    },
  ),
);

// --- selectors ---------------------------------------------------------------

export function selectedStep(state: AppState): Step | null {
  if (!state.manual || !state.selectedStepId) return null;
  return state.manual.steps.find((s) => s.id === state.selectedStepId) ?? null;
}

export function selectedStepIndex(state: AppState): number {
  if (!state.manual || !state.selectedStepId) return -1;
  return state.manual.steps.findIndex((s) => s.id === state.selectedStepId);
}

// --- helpers -----------------------------------------------------------------

function newStep(id: string): Step {
  return {
    id,
    title: "",
    description: "",
    view: null,
    dependsOn: [],
    added: [],
    connections: [],
  };
}

function resolveSelectedStep(manual: ManualDocument, prev: string | null): string | null {
  if (prev && manual.steps.some((s) => s.id === prev)) return prev;
  return manual.steps[0]?.id ?? null;
}

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export type { Connection };
