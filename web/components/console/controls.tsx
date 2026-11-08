"use client";

import { useId } from "react";

/**
 * The console's control vocabulary. Weights and confidences are set on notched
 * meters rather than sliders, because every one of these values is a small
 * whole number and a notch shows you the whole range at once.
 */

export function NotchMeter({
  name,
  value,
  min,
  max,
  onChange,
  disabled,
  label,
  tone = "signal",
  zeroDetent = false,
}: {
  name: string;
  value: number;
  min: number;
  max: number;
  onChange: (v: number) => void;
  disabled?: boolean;
  label: string;
  tone?: "signal" | "steel";
  zeroDetent?: boolean;
}) {
  const groupId = useId();
  const steps: number[] = [];
  for (let v = min; v <= max; v += 1) steps.push(v);

  return (
    <fieldset
      className="min-w-0"
      disabled={disabled}
      aria-describedby={`${groupId}-val`}
    >
      <legend className="sr-only">{label}</legend>
      <div className="flex items-end gap-[3px]">
        {steps.map((v) => {
          const negative = v < 0;
          const filled = zeroDetent
            ? (v > 0 && value >= v) ||
              (v < 0 && value <= v) ||
              (v === 0 && value === 0)
            : v <= value;
          const isZero = zeroDetent && v === 0;
          const fillClass = filled
            ? negative
              ? "bg-flag-lift"
              : tone === "steel"
                ? "bg-steel-lift"
                : "bg-signal"
            : "bg-rule-dark";

          return (
            <label
              key={v}
              className={`group relative cursor-pointer ${disabled ? "cursor-default" : ""}`}
              title={`${label}: ${v > 0 && zeroDetent ? "+" : ""}${v}`}
            >
              <input
                type="radio"
                name={`${name}-${groupId}`}
                value={v}
                checked={value === v}
                onChange={() => onChange(v)}
                className="sr-only peer"
              />
              <span
                aria-hidden
                className={`block w-2.5 transition-all ${fillClass} ${
                  isZero ? "h-2 w-1" : filled ? "h-7" : "h-3"
                } peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-signal ${
                  disabled ? "" : "group-hover:bg-signal-lift"
                }`}
              />
            </label>
          );
        })}
        <span
          id={`${groupId}-val`}
          className="ml-3 font-[family-name:var(--font-wire)] text-sm font-semibold tabular-nums shrink-0"
        >
          {zeroDetent && value > 0 ? "+" : ""}
          {value}
        </span>
      </div>
    </fieldset>
  );
}

export function Toggle({
  checked,
  onChange,
  label,
  disabled,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <label className="inline-flex items-center gap-2.5 cursor-pointer select-none">
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        className="sr-only peer"
      />
      <span
        aria-hidden
        className={`relative block h-5 w-9 border transition-colors peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-signal ${
          checked ? "bg-signal border-signal" : "bg-transparent border-rule-dark"
        }`}
      >
        <span
          className={`absolute top-[2px] block h-[14px] w-[14px] transition-all ${
            checked ? "left-[20px] bg-ink" : "left-[2px] bg-muted-dark"
          }`}
        />
      </span>
      <span className="wire-sm text-muted-dark">{label}</span>
    </label>
  );
}

export function SelectField({
  value,
  options,
  onChange,
  label,
  disabled,
}: {
  value: string;
  options: string[];
  onChange: (v: string) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <label className="block">
      <span className="sr-only">{label}</span>
      <select
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        className="w-full bg-ink-2 border border-rule-dark px-3 py-2 font-[family-name:var(--font-wire)] text-[0.8rem] text-paper focus:border-signal disabled:opacity-60"
      >
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </label>
  );
}

export function NumberField({
  value,
  onChange,
  label,
  unit,
  min,
  max,
  step,
  disabled,
}: {
  value: number;
  onChange: (v: number) => void;
  label: string;
  unit?: string;
  min?: number;
  max?: number;
  step?: number;
  disabled?: boolean;
}) {
  return (
    <label className="flex items-baseline gap-2">
      <span className="sr-only">{label}</span>
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        step={step}
        disabled={disabled}
        onChange={(e) => {
          const n = Number(e.target.value);
          if (!Number.isNaN(n)) onChange(n);
        }}
        className="w-28 bg-ink-2 border border-rule-dark px-3 py-2 font-[family-name:var(--font-wire)] text-[0.85rem] tabular-nums text-paper focus:border-signal disabled:opacity-60"
      />
      {unit ? <span className="wire-sm text-muted-dark">{unit}</span> : null}
    </label>
  );
}

export function TextArea({
  value,
  onChange,
  label,
  rows = 3,
  disabled,
  placeholder,
  grow = false,
}: {
  value: string;
  onChange: (v: string) => void;
  label: string;
  rows?: number;
  disabled?: boolean;
  placeholder?: string;
  grow?: boolean;
}) {
  return (
    <label className={grow ? "flex flex-col flex-1 min-h-0" : "block"}>
      <span className="sr-only">{label}</span>
      <textarea
        value={value}
        rows={rows}
        disabled={disabled}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className={`w-full bg-ink-2 border border-rule-dark px-3 py-2.5 text-[0.95rem] leading-relaxed text-paper placeholder:text-muted-dark focus:border-signal disabled:opacity-60 resize-y ${
          grow ? "flex-1" : ""
        }`}
      />
    </label>
  );
}

export function Chip({
  children,
  tone = "neutral",
}: {
  children: React.ReactNode;
  tone?: "neutral" | "signal" | "steel" | "flag";
}) {
  const tones = {
    neutral: "border-rule-dark text-muted-dark",
    signal: "border-signal text-signal",
    steel: "border-steel-lift text-steel-lift",
    flag: "border-flag-lift text-flag-lift",
  };
  return (
    <span className={`wire-sm border px-2 py-1 inline-block ${tones[tone]}`}>
      {children}
    </span>
  );
}
