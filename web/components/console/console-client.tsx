"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  fetchUserContext,
  isConnected,
  saveUserContextRow,
  USER_CONTEXT_TABLE,
} from "@/lib/supabase";
import { DEMO_USER_CONTEXT } from "@/lib/demo-data";
import type { UserContextPatch, UserContextRow } from "@/lib/types";
import { InterestsPanel } from "./interests-panel";
import { HypothesesPanel } from "./hypotheses-panel";
import { SourcesPanel } from "./sources-panel";
import { TuningPanel } from "./tuning-panel";

const TABS = [
  { id: "interests", label: "Interests", note: "weighted topics" },
  { id: "hypotheses", label: "Hypotheses", note: "claims under test" },
  { id: "sources", label: "Sources", note: "the feed registry" },
  { id: "tuning", label: "Tuning", note: "every engine knob" },
] as const;

type TabId = (typeof TABS)[number]["id"];

const FIELD_LABEL: Record<string, string> = {
  weight: "weight",
  active: "on or off",
  stance: "stance",
  confidence: "confidence",
  reasoning: "reasoning",
  specificity: "scope",
  status: "status",
  topic: "topic",
};

function show(v: unknown): string {
  if (v === true) return "on";
  if (v === false) return "off";
  if (v === null || v === undefined || v === "") return "empty";
  const s = String(v);
  return s.length > 60 ? `${s.slice(0, 57)}…` : s;
}

export function ConsoleClient() {
  const [rows, setRows] = useState<UserContextRow[]>(
    isConnected ? [] : DEMO_USER_CONTEXT,
  );
  const [loading, setLoading] = useState(isConnected);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [tab, setTab] = useState<TabId>("interests");

  const [drafts, setDrafts] = useState<Record<string, UserContextPatch>>({});
  const [reviewing, setReviewing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  useEffect(() => {
    if (!isConnected) return;
    let live = true;
    fetchUserContext()
      .then((data) => {
        if (!live) return;
        setRows(data);
        setLoading(false);
      })
      .catch((err: Error) => {
        if (!live) return;
        setLoadError(err.message);
        setRows(DEMO_USER_CONTEXT);
        setLoading(false);
      });
    return () => {
      live = false;
    };
  }, []);

  useEffect(() => {
    if (!reviewing) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setReviewing(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [reviewing]);

  const draftFor = useCallback(
    (id: string) => drafts[id] ?? {},
    [drafts],
  );

  const onEdit = useCallback(
    (id: string, patch: UserContextPatch) => {
      setSaved(null);
      setSaveError(null);
      setDrafts((d) => {
        const row = rows.find((r) => r.id === id);
        const merged = { ...(d[id] ?? {}), ...patch } as UserContextPatch;
        // drop any field that is back at its stored value
        if (row) {
          for (const key of Object.keys(merged) as (keyof UserContextPatch)[]) {
            if (merged[key] === row[key]) delete merged[key];
          }
        }
        const next = { ...d };
        if (Object.keys(merged).length === 0) delete next[id];
        else next[id] = merged;
        return next;
      });
    },
    [rows],
  );

  const changes = useMemo(() => {
    return Object.entries(drafts).flatMap(([id, patch]) => {
      const row = rows.find((r) => r.id === id);
      if (!row) return [];
      return Object.entries(patch).map(([field, value]) => ({
        id,
        topic: row.topic,
        field,
        from: row[field as keyof UserContextRow],
        to: value,
      }));
    });
  }, [drafts, rows]);

  const rowsChanged = Object.keys(drafts).length;

  async function applyChanges() {
    setSaving(true);
    setSaveError(null);

    if (!isConnected) {
      setRows((rs) =>
        rs.map((r) => (drafts[r.id] ? { ...r, ...drafts[r.id] } : r)),
      );
      setDrafts({});
      setSaving(false);
      setReviewing(false);
      setSaved(
        "Applied to the sample data on this page only. Nothing was written to a database.",
      );
      return;
    }

    try {
      const updated: UserContextRow[] = [];
      for (const [id, patch] of Object.entries(drafts)) {
        updated.push(await saveUserContextRow(id, patch));
      }
      setRows((rs) =>
        rs.map((r) => updated.find((u) => u.id === r.id) ?? r),
      );
      setDrafts({});
      setReviewing(false);
      setSaved(
        `Saved ${updated.length} row${updated.length === 1 ? "" : "s"} to ${USER_CONTEXT_TABLE} and read them back.`,
      );
    } catch (err) {
      setSaveError((err as Error).message);
    } finally {
      setSaving(false);
    }
  }

  const interests = rows.filter((r) => r.kind === "interest");
  const hypotheses = rows.filter((r) => r.kind === "hypothesis");
  const demo = !isConnected || Boolean(loadError);

  return (
    <div className="pb-40">
      <ConnectionBanner demo={demo} loadError={loadError} />

      {/* ---------- tabs ---------- */}
      <div className="shell">
        <div
          role="tablist"
          aria-label="Console sections"
          className="flex flex-wrap gap-x-8 gap-y-2 border-b border-rule-dark"
        >
          {TABS.map((t) => {
            const active = t.id === tab;
            return (
              <button
                key={t.id}
                role="tab"
                type="button"
                aria-selected={active}
                aria-controls={`panel-${t.id}`}
                id={`tab-${t.id}`}
                onClick={() => setTab(t.id)}
                className={`text-left pt-4 pb-3 border-b-2 -mb-px transition-colors ${
                  active
                    ? "border-signal text-paper"
                    : "border-transparent text-muted-dark hover:text-paper"
                }`}
              >
                <span className="block font-[family-name:var(--font-display)] text-lg font-bold">
                  {t.label}
                </span>
                <span className="wire-sm block mt-1 opacity-70">{t.note}</span>
              </button>
            );
          })}
        </div>

        <div
          id={`panel-${tab}`}
          role="tabpanel"
          aria-labelledby={`tab-${tab}`}
          className="pt-10"
        >
          {loading ? (
            <p className="wire text-muted-dark py-16">Reading the table…</p>
          ) : (
            <>
              {tab === "interests" ? (
                <InterestsPanel
                  rows={interests}
                  draftFor={draftFor}
                  onEdit={onEdit}
                  busy={saving}
                />
              ) : null}
              {tab === "hypotheses" ? (
                <HypothesesPanel
                  rows={hypotheses}
                  draftFor={draftFor}
                  onEdit={onEdit}
                  busy={saving}
                />
              ) : null}
              {tab === "sources" ? <SourcesPanel /> : null}
              {tab === "tuning" ? <TuningPanel /> : null}
            </>
          )}
        </div>
      </div>

      {saved ? (
        <div className="shell mt-8">
          <p
            role="status"
            className="border border-steel-lift text-steel-lift px-4 py-3 text-sm"
          >
            {saved}
          </p>
        </div>
      ) : null}

      {/* ---------- pending changes tray ---------- */}
      {rowsChanged > 0 ? (
        <div className="fixed inset-x-0 bottom-0 z-40 bg-ink-2 border-t-2 border-signal">
          <div className="shell py-4 flex flex-wrap items-center gap-x-6 gap-y-3">
            <p className="wire text-signal">
              {changes.length} change{changes.length === 1 ? "" : "s"} waiting
            </p>
            <p className="text-sm text-muted-dark">
              Nothing is written until you confirm it.
            </p>
            <div className="flex gap-3 ml-auto">
              <button
                type="button"
                onClick={() => setDrafts({})}
                className="wire border border-rule-dark text-muted-dark px-5 py-3 hover:text-paper hover:border-paper transition-colors"
              >
                Discard
              </button>
              <button
                type="button"
                onClick={() => setReviewing(true)}
                className="wire bg-signal text-ink px-5 py-3 hover:bg-signal-lift transition-colors"
              >
                Review changes
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {/* ---------- confirm ---------- */}
      {reviewing ? (
        <div
          className="fixed inset-0 z-50 bg-ink/85 flex items-end sm:items-center justify-center p-0 sm:p-6"
          onClick={(e) => {
            if (e.target === e.currentTarget) setReviewing(false);
          }}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="confirm-title"
            className="bg-ink border border-signal w-full max-w-2xl max-h-[85vh] overflow-y-auto"
          >
            <div className="p-6 sm:p-8">
              <p className="wire-sm text-signal mb-3">
                {demo ? "Sample data" : USER_CONTEXT_TABLE}
              </p>
              <h2 id="confirm-title" className="text-2xl text-paper">
                {demo
                  ? "Apply these changes to the sample?"
                  : "Write these changes to Supabase?"}
              </h2>
              <p className="text-muted-dark mt-3 text-sm leading-relaxed">
                {demo
                  ? "There are no database credentials in this deployment, so this only updates what is on screen. It shows you exactly what a real save would send."
                  : "Each row is updated and then read straight back, so what you see afterwards is what the table actually holds."}
              </p>

              <ul className="mt-6 border-t border-rule-dark">
                {changes.map((c, i) => (
                  <li
                    key={`${c.id}-${c.field}-${i}`}
                    className="border-b border-rule-dark py-4"
                  >
                    <p className="text-paper leading-snug">{c.topic}</p>
                    <p className="mt-2 flex flex-wrap items-baseline gap-2 font-[family-name:var(--font-wire)] text-sm">
                      <span className="text-muted-dark">
                        {FIELD_LABEL[c.field] ?? c.field}
                      </span>
                      <span className="text-muted-dark line-through">
                        {show(c.from)}
                      </span>
                      <span className="text-signal">→</span>
                      <span className="text-signal">{show(c.to)}</span>
                    </p>
                  </li>
                ))}
              </ul>

              {saveError ? (
                <p className="mt-5 border border-flag-lift text-flag-lift px-4 py-3 text-sm">
                  The write did not go through. {saveError}
                </p>
              ) : null}

              <div className="mt-7 flex flex-wrap gap-3">
                <button
                  type="button"
                  disabled={saving}
                  onClick={applyChanges}
                  className="wire bg-signal text-ink px-6 py-3.5 hover:bg-signal-lift transition-colors disabled:opacity-60"
                >
                  {saving
                    ? "Working…"
                    : demo
                      ? "Apply to the sample"
                      : "Write to Supabase"}
                </button>
                <button
                  type="button"
                  disabled={saving}
                  onClick={() => setReviewing(false)}
                  className="wire border border-rule-dark text-muted-dark px-6 py-3.5 hover:text-paper hover:border-paper transition-colors"
                >
                  Back
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function ConnectionBanner({
  demo,
  loadError,
}: {
  demo: boolean;
  loadError: string | null;
}) {
  return (
    <div className="shell pt-10 pb-8">
      <div className="grid gap-x-10 gap-y-6 lg:grid-cols-[minmax(0,1fr)_auto] items-end">
        <div>
          <p className="wire text-muted-dark">The working surface</p>
          <h1 className="mt-4 text-[length:var(--text-section)] text-paper">
            Console
          </h1>
          <p className="mt-4 text-muted-dark max-w-[58ch] leading-relaxed">
            Everything the engine reads before it decides what matters. Interests
            and hypotheses come from one Supabase table. Sources and tuning are
            shown as they are, so the whole configured surface has somewhere to
            be seen.
          </p>
        </div>

        <div
          className={`border px-5 py-4 max-w-md ${
            demo ? "border-signal" : "border-steel-lift"
          }`}
        >
          <p
            className={`wire-sm flex items-center gap-2.5 ${
              demo ? "text-signal" : "text-steel-lift"
            }`}
          >
            <span
              aria-hidden
              className={`inline-block h-2.5 w-2.5 ${
                demo ? "bg-signal" : "bg-steel-lift"
              }`}
            />
            {demo ? "Demo data, not connected" : "Connected to Supabase"}
          </p>
          <p className="text-sm text-muted-dark mt-2.5 leading-relaxed">
            {loadError
              ? `The table could not be read, so the sample is showing instead. ${loadError}`
              : demo
                ? `No database credentials are set for this deployment, so the rows below are a sample in the same shape as the real ${USER_CONTEXT_TABLE} table. Editing works, saving is held here.`
                : `Reading and writing the live ${USER_CONTEXT_TABLE} table.`}
          </p>
        </div>
      </div>
    </div>
  );
}
