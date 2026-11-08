"use client";

import type { UserContextRow, UserContextPatch } from "@/lib/types";
import { NotchMeter, Toggle } from "./controls";

/**
 * Interests. One row per topic, with a signed weight from -3 to +3 and an
 * on/off switch. The weight is a direct nudge on every relevance score, so
 * pushing a topic to -3 is how you stop hearing about it.
 */
export function InterestsPanel({
  rows,
  draftFor,
  onEdit,
  busy,
}: {
  rows: UserContextRow[];
  draftFor: (id: string) => UserContextPatch;
  onEdit: (id: string, patch: UserContextPatch) => void;
  busy: boolean;
}) {
  if (rows.length === 0) {
    return (
      <p className="text-muted-dark py-12">
        No interests on file. Add a row to the user_context table with kind set
        to interest, and it shows up here.
      </p>
    );
  }

  return (
    <div>
      <div className="grid gap-x-10 gap-y-6 md:grid-cols-[minmax(0,1fr)_auto] items-baseline pb-8">
        <p className="text-muted-dark max-w-[62ch] leading-relaxed">
          A signed weight from minus three to plus three. Plus three pushes a
          matching article up by about three points out of ten. Minus three
          pushes it down by the same amount, which is how a topic stops reaching
          you without banning any source that covers it.
        </p>
        <p className="wire-sm text-muted-dark md:text-right">
          <span className="text-flag-lift">−3 quieter</span>
          <span className="mx-2">·</span>
          <span className="text-signal">+3 louder</span>
        </p>
      </div>

      <ul className="border-t border-rule-dark">
        {rows.map((row) => {
          const draft = draftFor(row.id);
          const weight = draft.weight ?? row.weight ?? 0;
          const active = draft.active ?? row.active;
          const changed = Object.keys(draft).length > 0;

          return (
            <li
              key={row.id}
              className={`grid gap-x-8 gap-y-4 md:grid-cols-[minmax(0,1fr)_15rem_7rem] items-center border-b border-rule-dark py-5 ${
                active ? "" : "opacity-55"
              } ${changed ? "bg-signal/5 -mx-4 px-4" : ""}`}
            >
              <div className="min-w-0">
                <p className="text-lg leading-snug">{row.topic}</p>
                {changed ? (
                  <p className="wire-sm text-signal mt-1.5">Edited, not saved</p>
                ) : null}
              </div>

              <NotchMeter
                name={`weight-${row.id}`}
                label={`Weight for ${row.topic}`}
                value={weight}
                min={-3}
                max={3}
                zeroDetent
                disabled={busy || !active}
                onChange={(v) => onEdit(row.id, { weight: v })}
              />

              <Toggle
                checked={active}
                disabled={busy}
                label={active ? "On" : "Off"}
                onChange={(v) => onEdit(row.id, { active: v })}
              />
            </li>
          );
        })}
      </ul>
    </div>
  );
}
