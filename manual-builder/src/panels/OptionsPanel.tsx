import { Field, NumberInput, Section, Toggle } from "../components/fields";
import { useAppStore } from "../store/useAppStore";
import type { UpAxis } from "../types/manual";

/** Manual-wide defaults and viewport display options. */
export function OptionsPanel() {
  const manual = useAppStore((s) => s.manual);
  const updateDefaults = useAppStore((s) => s.updateDefaults);
  const ui = useAppStore((s) => s.ui);
  const setUi = useAppStore((s) => s.setUi);
  const explodeScale = useAppStore((s) => s.explodeScale);
  const setExplodeScale = useAppStore((s) => s.setExplodeScale);

  if (!manual) return <div className="panel-empty">No manual loaded.</div>;
  const defaults = manual.defaults;

  return (
    <div className="panel panel--inspector">
      <Section title="Defaults">
        <Field label="Up axis">
          <select
            className="input"
            value={defaults.upAxis}
            onChange={(e) => updateDefaults({ upAxis: e.target.value as UpAxis })}
          >
            <option value="z">Z (CAD default)</option>
            <option value="y">Y</option>
            <option value="x">X</option>
          </select>
        </Field>

        <div className="subhead">Default view</div>
        <Field label="Azimuth°">
          <NumberInput
            value={defaults.view.azimuthDeg}
            onChange={(n) => updateDefaults({ view: { ...defaults.view, azimuthDeg: n } })}
          />
        </Field>
        <Field label="Elevation°">
          <NumberInput
            value={defaults.view.elevationDeg}
            onChange={(n) => updateDefaults({ view: { ...defaults.view, elevationDeg: n } })}
          />
        </Field>
        <Field label="Zoom">
          <NumberInput
            value={defaults.view.zoom}
            step={0.05}
            min={0.05}
            onChange={(n) => updateDefaults({ view: { ...defaults.view, zoom: n } })}
          />
        </Field>
      </Section>

      <Section title="Display">
        <Field label={`Explode scale  ${Math.round(explodeScale * 100)}%`}>
          <input
            type="range"
            className="input input--range"
            min={0}
            max={1}
            step={0.01}
            value={explodeScale}
            onChange={(e) => setExplodeScale(parseFloat(e.target.value))}
          />
        </Field>
        <Toggle
          label="Show sheet labels"
          checked={ui.showLabels}
          onChange={(b) => setUi({ showLabels: b })}
        />
        <Toggle
          label="Show built parts"
          checked={ui.showCompleted}
          onChange={(b) => setUi({ showCompleted: b })}
        />
        <Toggle
          label="Always show vertices"
          checked={ui.showVertices}
          onChange={(b) => setUi({ showVertices: b })}
        />
        <Toggle
          label="Show origin axes"
          checked={ui.showOrigin}
          onChange={(b) => setUi({ showOrigin: b })}
        />
      </Section>
    </div>
  );
}
