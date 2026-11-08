"use client";

import {
  HYPOTHESIS_STATUSES,
  SPECIFICITIES,
  STANCES,
  type UserContextRow,
  type UserContextPatch,
} from "@/lib/types";
import { NotchMeter, Toggle, SelectField, TextArea, Chip } from "./controls";

const STATUS_TONE: Record<string, "signal" | "steel" | "flag" | "neutral"> = {
  active: "signal",
  partially_confirmed: "steel",
  pending_confirmation: "neutral",
  confirmed: "steel",
  retired: "neutral",
};

/**
 * Hypotheses. A claim you are testing, your stance, how sure you are, and what
 * would change your mind. The analyst reads these on every run and says in the
 * brief whether an article aligns with your position or challenges it.
 */
export function HypothesesPanel({
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
        No hypotheses on file. Add a row to the user_context table with kind set
        to hypothesis, and it shows up here.
      </p>
    );
  }

  return (
    <div>
      <p className="text-muted-dark max-w-[68ch] leading-relaxed pb-8">
        Only hypotheses that are on, and whose status is active, partially
        confirmed or pending confirmation, are fed to the analyst. Retiring one
        keeps the record without spending anything on it.
      </p>

      <ul className="border-t border-rule-dark">
        {rows.map((row) => {
          const draft = draftFor(row.id);
          const stance = draft.stance ?? row.stance ?? "neutral";
          const confidence = draft.confidence ?? row.confidence ?? 0;
          const reasoning = draft.reasoning ?? row.reasoning ?? "";
          const status = draft.status ?? row.status ?? "active";
          const specificity = draft.specificity ?? row.specificity ?? "broad";
          const active = draft.active ?? row.active;
          const changed = Object.keys(draft).length > 0;

          return (
            <li
              key={row.id}
              className={`border-b border-rule-dark py-7 ${
                active ? "" : "opacity-55"
              } ${changed ? "bg-signal/5 -mx-4 px-4" : ""}`}
            >
              <div className="flex flex-wrap items-start justify-between gap-x-8 gap-y-3">
                <p className="text-lg leading-snug max-w-[60ch]">{row.topic}</p>
                <div className="flex items-center gap-3 shrink-0">
                  <Chip tone={STATUS_TONE[status] ?? "neutral"}>
                    {status.replace(/_/g, " ")}
                  </Chip>
                  <Toggle
                    checked={active}
                    disabled={busy}
                    label={active ? "On" : "Off"}
                    onChange={(v) => onEdit(row.id, { active: v })}
                  />
                </div>
              </div>

              {changed ? (
                <p className="wire-sm text-signal mt-2">Edited, not saved</p>
              ) : null}

              <div className="mt-5 grid gap-x-10 gap-y-6 lg:grid-cols-[minmax(0,1fr)_18rem]">
                <div className="flex flex-col min-h-0">
                  <p className="wire-sm text-muted-dark mb-2">
                    Why you hold it, and what would change it
                  </p>
                  <TextArea
                    label={`Reasoning for ${row.topic}`}
                    value={reasoning}
                    rows={4}
                    grow
                    disabled={busy}
                    placeholder="One or two sentences."
                    onChange={(v) => onEdit(row.id, { reasoning: v })}
                  />
                </div>

                <div className="grid gap-5 content-start">
                  <div>
                    <p className="wire-sm text-muted-dark mb-2">
                      Confidence out of ten
                    </p>
                    <NotchMeter
                      name={`confidence-${row.id}`}
                      label={`Confidence for ${row.topic}`}
                      value={confidence}
                      min={0}
                      max={10}
                      tone="steel"
                      disabled={busy}
                      onChange={(v) => onEdit(row.id, { confidence: v })}
                    />
                  </div>

                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <p className="wire-sm text-muted-dark mb-2">Stance</p>
                      <SelectField
                        label={`Stance for ${row.topic}`}
                        value={stance}
                        disabled={busy}
                        options={
                          STANCES.includes(stance as (typeof STANCES)[number])
                            ? [...STANCES]
                            : [stance, ...STANCES]
                        }
                        onChange={(v) => onEdit(row.id, { stance: v })}
                      />
                    </div>
                    <div>
                      <p className="wire-sm text-muted-dark mb-2">Scope</p>
                      <SelectField
                        label={`Specificity for ${row.topic}`}
                        value={specificity}
                        disabled={busy}
                        options={[...SPECIFICITIES]}
                        onChange={(v) => onEdit(row.id, { specificity: v })}
                      />
                    </div>
                  </div>

                  <div>
                    <p className="wire-sm text-muted-dark mb-2">Status</p>
                    <SelectField
                      label={`Status for ${row.topic}`}
                      value={status}
                      disabled={busy}
                      options={HYPOTHESIS_STATUSES}
                      onChange={(v) => onEdit(row.id, { status: v })}
                    />
                  </div>
                </div>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
