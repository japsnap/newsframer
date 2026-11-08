"use client";

import { useState } from "react";
import { SAMPLE_SOURCES, SOURCE_TOTALS } from "@/lib/sources-data";
import { Chip } from "./controls";

const BIAS_TONE = {
  left: "steel",
  center: "neutral",
  right: "signal",
} as const;

/**
 * Sources. Read only, and labelled as such. The engine both reads and writes
 * this table during a run, so a browser write would race it. This panel shows
 * the model so the shape is visible while that write path does not exist.
 */
export function SourcesPanel() {
  const [bundle, setBundle] = useState<string>("all");

  const bundles = ["all", ...SOURCE_TOTALS.perBundle.map((b) => b.name)];
  const shown =
    bundle === "all"
      ? SAMPLE_SOURCES
      : SAMPLE_SOURCES.filter((s) => s.category === bundle);

  const maxWeight = 1;

  return (
    <div>
      <div className="grid gap-x-10 gap-y-6 lg:grid-cols-[minmax(0,1fr)_auto] items-start pb-8">
        <p className="text-muted-dark max-w-[64ch] leading-relaxed">
          The registry holds {SOURCE_TOTALS.sources} sources across{" "}
          {SOURCE_TOTALS.bundles} bundles. Each one carries an editorial weight,
          its own freshness window, and a bias and factuality tag that the
          pipeline uses to keep one sided coverage visible rather than silent.
          Below is a sample of the shape, taken from the engine's seed file.
        </p>
        <div className="border border-signal px-4 py-3 max-w-md">
          <p className="wire-sm text-signal">Read only in v1</p>
          <p className="text-sm text-muted-dark mt-2 leading-relaxed">
            The engine writes to this table mid run, updating counters and last
            fetched times. A browser write would race it, so nothing here is
            editable until the engine exposes a safe write path.
          </p>
        </div>
      </div>

      <div className="flex flex-wrap gap-2 pb-6">
        {bundles.map((b) => (
          <button
            key={b}
            type="button"
            onClick={() => setBundle(b)}
            className={`wire-sm border px-3 py-1.5 transition-colors ${
              bundle === b
                ? "border-signal bg-signal text-ink"
                : "border-rule-dark text-muted-dark hover:border-signal hover:text-signal"
            }`}
          >
            {b}
            {b !== "all" ? (
              <span className="ml-2 opacity-70">
                {SOURCE_TOTALS.perBundle.find((x) => x.name === b)?.count}
              </span>
            ) : null}
          </button>
        ))}
      </div>

      <div className="overflow-x-auto -mx-5 px-5 md:mx-0 md:px-0">
        <table className="w-full min-w-[52rem] border-collapse text-left">
          <thead>
            <tr className="border-y border-rule-dark">
              <th className="wire-sm text-muted-dark py-3 pr-4 font-medium">
                Source
              </th>
              <th className="wire-sm text-muted-dark py-3 pr-4 font-medium">
                Bundle
              </th>
              <th className="wire-sm text-muted-dark py-3 pr-4 font-medium">
                Weight
              </th>
              <th className="wire-sm text-muted-dark py-3 pr-4 font-medium">
                Window
              </th>
              <th className="wire-sm text-muted-dark py-3 pr-4 font-medium">
                Fetch
              </th>
              <th className="wire-sm text-muted-dark py-3 font-medium">
                Bias / factuality
              </th>
            </tr>
          </thead>
          <tbody>
            {shown.map((s) => (
              <tr key={s.name} className="border-b border-rule-dark align-top">
                <td className="py-4 pr-4">
                  <span className="text-[1.05rem]">{s.name}</span>
                  <span className="wire-sm text-muted-dark block mt-1">
                    {s.source_type}
                    {s.scrape_days ? ` · scraped ${s.scrape_days}` : ""}
                  </span>
                </td>
                <td className="py-4 pr-4">
                  <span className="wire-sm text-muted-dark">{s.category}</span>
                </td>
                <td className="py-4 pr-4 w-40">
                  <span className="flex items-center gap-2.5">
                    <span
                      aria-hidden
                      className="h-1.5 bg-rule-dark w-20 block relative"
                    >
                      <span
                        className="absolute inset-y-0 left-0 bg-signal"
                        style={{ width: `${(s.weight / maxWeight) * 100}%` }}
                      />
                    </span>
                    <span className="font-[family-name:var(--font-wire)] text-xs tabular-nums text-muted-dark">
                      {s.weight.toFixed(1)}
                    </span>
                  </span>
                </td>
                <td className="py-4 pr-4">
                  <span className="font-[family-name:var(--font-wire)] text-sm tabular-nums">
                    {s.fetch_window_hours}
                  </span>
                  <span className="wire-sm text-muted-dark ml-1.5">h</span>
                </td>
                <td className="py-4 pr-4">
                  <span className="wire-sm text-muted-dark">
                    {s.fetch_mode === "rss" ? "rss" : "browser"}
                  </span>
                </td>
                <td className="py-4">
                  {s.bias ? (
                    <span className="flex flex-wrap items-center gap-2">
                      <Chip tone={BIAS_TONE[s.bias]}>{s.bias}</Chip>
                      {s.factuality ? (
                        <span className="wire-sm text-muted-dark">
                          {s.factuality}
                        </span>
                      ) : null}
                    </span>
                  ) : (
                    <span className="wire-sm text-muted-dark opacity-50">
                      not tagged
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="text-sm text-muted-dark mt-6 leading-relaxed max-w-[64ch]">
        Bias tags matter downstream. In geopolitics and Pakistan the same story
        collapse keeps one left, one centre and one right source when they exist,
        and a theme built from one lean only carries a warning line in the brief.
      </p>
    </div>
  );
}
