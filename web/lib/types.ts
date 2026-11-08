/**
 * Shapes mirrored from the NewsFramer engine.
 *
 * `UserContextRow` matches the Supabase table `user_context` (see the engine's
 * user_context.example.sql). Interests carry a signed weight. Hypotheses carry
 * stance, confidence, reasoning, specificity and status.
 */

export type ContextKind = "interest" | "hypothesis";

export type HypothesisStatus =
  | "active"
  | "partially_confirmed"
  | "pending_confirmation"
  | "confirmed"
  | "retired";

export const HYPOTHESIS_STATUSES: HypothesisStatus[] = [
  "active",
  "partially_confirmed",
  "pending_confirmation",
  "confirmed",
  "retired",
];

export const STANCES = ["bullish", "bearish", "neutral", "skeptical"] as const;
export const SPECIFICITIES = ["specific", "broad"] as const;

export interface UserContextRow {
  id: string;
  kind: ContextKind;
  topic: string;
  /** interests: signed relevance nudge, -3..+3 */
  weight: number | null;
  /** hypotheses: your directional position */
  stance: string | null;
  /** hypotheses: 0..10 */
  confidence: number | null;
  /** hypotheses: why you hold it, what would change it */
  reasoning: string | null;
  specificity: string | null;
  status: string | null;
  active: boolean;
  created_at?: string;
}

/** The columns of a row the console is allowed to change. */
export type UserContextPatch = Partial<
  Pick<
    UserContextRow,
    | "topic"
    | "weight"
    | "stance"
    | "confidence"
    | "reasoning"
    | "specificity"
    | "status"
    | "active"
  >
>;

/**
 * Mirrors the engine's `sources` table. The console shows these read-only:
 * the engine reads and writes them directly, and there is no safe write path
 * from a browser yet.
 */
export interface SourceRow {
  name: string;
  category: string;
  weight: number;
  source_type: string;
  has_rss: boolean;
  fetch_mode: "rss" | "browser_required";
  /** per-source freshness window, in hours */
  fetch_window_hours: number;
  region: string | null;
  bias: "left" | "center" | "right" | null;
  factuality: "High" | "Mixed" | "Low" | null;
  /** JST weekday scrape calendar, e.g. "tue" */
  scrape_days: string | null;
  active: boolean;
}

/** One tunable read out of the engine's config/models.yaml. */
export type KnobType = "model" | "number" | "boolean" | "text" | "list";

export interface Knob {
  key: string;
  label: string;
  type: KnobType;
  value: string | number | boolean;
  /** plain-English explanation of what moving this does */
  note: string;
  unit?: string;
  min?: number;
  max?: number;
  step?: number;
  options?: string[];
}

export interface KnobGroup {
  /** the pipeline stage this rack belongs to */
  stage: string;
  title: string;
  blurb: string;
  knobs: Knob[];
}
