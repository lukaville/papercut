import type { ReactNode } from "react";
import type { Vec3 } from "../types/model";

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      <span className="field-control">{children}</span>
    </label>
  );
}

export function NumberInput({
  value,
  onChange,
  step = 1,
  min,
  max,
}: {
  value: number;
  onChange: (n: number) => void;
  step?: number;
  min?: number;
  max?: number;
}) {
  return (
    <input
      type="number"
      className="input input--number"
      value={Number.isFinite(value) ? value : 0}
      step={step}
      min={min}
      max={max}
      onChange={(e) => {
        const n = parseFloat(e.target.value);
        if (!Number.isNaN(n)) onChange(n);
      }}
    />
  );
}

export function Vec3Input({
  value,
  onChange,
  step = 0.1,
}: {
  value: Vec3;
  onChange: (v: Vec3) => void;
  step?: number;
}) {
  return (
    <span className="vec3">
      {[0, 1, 2].map((axis) => (
        <NumberInput
          key={axis}
          value={value[axis]}
          step={step}
          onChange={(n) => {
            const next = value.slice() as Vec3;
            next[axis] = n;
            onChange(next);
          }}
        />
      ))}
    </span>
  );
}

export function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (b: boolean) => void;
  label: string;
}) {
  return (
    <label className="toggle">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span>{label}</span>
    </label>
  );
}

export function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="section">
      <h3 className="section-title">{title}</h3>
      {children}
    </section>
  );
}
