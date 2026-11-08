"use client";

import { useEffect, useState } from "react";
import { TUNING_GROUPS } from "@/lib/tuning-data";
import type { Knob } from "@/lib/types";
import { NumberField, SelectField, Toggle } from "./controls";

const STORE_KEY = "newsframer.tuning.draft";

type Draft = Record<string, string | number | boolean>;

/**
 * Tuning. The engine reads its own config/models.yaml off disk on every run, so
 * this panel is a viewer: it shows every knob, what it is set to, and what
 * moving it would do. Your changes stay in this browser so you can work out a
 * change before you make it in the file.
 */
export function TuningPanel() {
  const [draft, setDraft] = useState<Draft>({});
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(STORE_KEY);
      if (raw) setDraft(JSON.parse(raw) as Draft);
    } catch {
      // a corrupt or blocked store just means we start from the engine values
    }
    setLoaded(true);
  }, []);

  useEffect(() => {
    if (!loaded) return;
    try {
      window.localStorage.setItem(STORE_KEY, JSON.stringify(draft));
    } catch {
      // storage can be full or blocked; the panel still works for this session
    }
  }, [draft, loaded]);

  const changedCount = Object.keys(draft).length;

  function set(key: string, value: string | number | boolean, engine: Knob["value"]) {
    setDraft((d) => {
      const next = { ...d };
      if (value === engine) delete next[key];
      else next[key] = value;
      return next;
    });
  }

  function resetAll() {
    setDraft({});
  }

  return (
    <div>
      <div className="grid gap-x-10 gap-y-6 lg:grid-cols-[minmax(0,1fr)_auto] items-start pb-8">
        <p className="text-muted-dark max-w-[64ch] leading-relaxed">
          Every operational number in the pipeline lives in one file, and none of
          it is hardcoded. This is that file, grouped by the stage it affects,
          with each knob explained in plain terms.
        </p>
        <div className="border border-signal px-4 py-3 max-w-md">
          <p className="wire-sm text-signal">Viewer in v1</p>
          <p className="text-sm text-muted-dark mt-2 leading-relaxed">
            The engine reads its yaml from the machine it runs on, which this
            page cannot reach. Changes you make here are kept in this browser as
            a plan, and are never sent anywhere.
          </p>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-x-5 gap-y-3 border-t border-rule-dark py-4 mb-8">
        <p className="wire-sm text-muted-dark">
          {changedCount === 0
            ? "Matching the engine"
            : `${changedCount} knob${changedCount === 1 ? "" : "s"} changed in this browser`}
        </p>
        {changedCount > 0 ? (
          <button
            type="button"
            onClick={resetAll}
            className="wire-sm border border-signal text-signal px-3 py-1.5 hover:bg-signal hover:text-ink transition-colors"
          >
            Put everything back
          </button>
        ) : null}
      </div>

      <div className="grid gap-14">
        {TUNING_GROUPS.map((group) => (
          <section key={`${group.stage}-${group.title}`}>
            <div className="grid gap-x-10 gap-y-3 md:grid-cols-[minmax(0,22rem)_minmax(0,1fr)] items-baseline border-t border-rule-dark pt-5 mb-6">
              <div>
                <p className="wire-sm text-signal mb-2">{group.stage}</p>
                <h3 className="text-xl">{group.title}</h3>
              </div>
              <p className="text-sm text-muted-dark leading-relaxed max-w-[60ch]">
                {group.blurb}
              </p>
            </div>

            <ul>
              {group.knobs.map((knob) => {
                const current = draft[knob.key] ?? knob.value;
                const changed = knob.key in draft;

                return (
                  <li
                    key={knob.key}
                    className={`grid gap-x-10 gap-y-3 md:grid-cols-[minmax(0,1fr)_16rem] items-start border-b border-rule-dark py-5 ${
                      changed ? "bg-signal/5 -mx-4 px-4" : ""
                    }`}
                  >
                    <div className="min-w-0">
                      <p className="text-[1.05rem]">{knob.label}</p>
                      <p className="font-[family-name:var(--font-wire)] text-[0.7rem] text-muted-dark mt-1 break-all">
                        {knob.key}
                      </p>
                      <p className="text-sm text-muted-dark mt-2 leading-relaxed max-w-[58ch]">
                        {knob.note}
                      </p>
                    </div>

                    <div className="md:justify-self-end w-full md:w-auto">
                      {knob.type === "boolean" ? (
                        <Toggle
                          checked={Boolean(current)}
                          label={current ? "On" : "Off"}
                          onChange={(v) => set(knob.key, v, knob.value)}
                        />
                      ) : null}

                      {knob.type === "number" ? (
                        <NumberField
                          label={knob.label}
                          value={Number(current)}
                          unit={knob.unit}
                          min={knob.min}
                          max={knob.max}
                          step={knob.step}
                          onChange={(v) => set(knob.key, v, knob.value)}
                        />
                      ) : null}

                      {(knob.type === "model" || knob.type === "text") &&
                      knob.options ? (
                        <SelectField
                          label={knob.label}
                          value={String(current)}
                          options={knob.options}
                          onChange={(v) => set(knob.key, v, knob.value)}
                        />
                      ) : null}

                      {knob.type === "list" ||
                      ((knob.type === "text" || knob.type === "model") &&
                        !knob.options) ? (
                        <p className="font-[family-name:var(--font-wire)] text-[0.8rem] text-muted-dark border border-rule-dark px-3 py-2">
                          {String(current)}
                        </p>
                      ) : null}

                      {changed ? (
                        <p className="wire-sm text-signal mt-2 md:text-right">
                          engine: {String(knob.value)}
                        </p>
                      ) : null}
                    </div>
                  </li>
                );
              })}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}
