/**
 * The filter cascade. Six bands, one per pipeline stage, each drawn as a row of
 * article ticks. Solid ticks survived the stage. Faint ticks were dropped.
 * The staircase collapsing to the left is the whole product in one picture.
 *
 * Counts are for a typical run and are derived from the engine's own config:
 * 61 sources at 10 items each, roughly 150 scored per run, a cutoff of 6 out of
 * 10, and nine themes from six active bundles.
 */

const SLOTS = 96;

type Tone = "signal" | "steel" | "ink";

interface Stage {
  n: string;
  name: string;
  alive: number;
  count: string;
  detail: string;
  tone: Tone;
}

const STAGES: Stage[] = [
  {
    n: "01",
    name: "Fetch",
    alive: 96,
    count: "~600",
    detail: "61 sources pulled, each on its own freshness window",
    tone: "ink",
  },
  {
    n: "02",
    name: "Classify",
    alive: 96,
    count: "~600",
    detail: "Labelled time sensitive or worth keeping warm",
    tone: "ink",
  },
  {
    n: "03",
    name: "Deduplicate",
    alive: 24,
    count: "~150",
    detail: "Five wire copies of one story collapse to the originator",
    tone: "steel",
  },
  {
    n: "04",
    name: "Analyze",
    alive: 24,
    count: "~150",
    detail: "Every survivor scored 0 to 10 against your own list",
    tone: "steel",
  },
  {
    n: "05",
    name: "Write",
    alive: 7,
    count: "41",
    detail: "Only these clear the cutoff, and become 9 themes",
    tone: "signal",
  },
  {
    n: "06",
    name: "Deliver",
    alive: 2,
    count: "2",
    detail: "Telegram at 06:00, WhatsApp at 11:00, recorded on confirmed send",
    tone: "signal",
  },
];

/* Navy at the raw end, amber at the delivered end. The ramp is the point:
   the pool starts as undifferentiated ink and ends as the one accent. */
const TONE_CLASS: Record<Tone, string> = {
  ink: "bg-ink",
  steel: "bg-steel",
  signal: "bg-signal",
};

function Band({ stage, index }: { stage: Stage; index: number }) {
  return (
    <li className="grid grid-cols-[2.25rem_1fr] gap-x-3 sm:grid-cols-[2.5rem_7.5rem_1fr] sm:gap-x-5 items-baseline py-3.5 border-t border-rule first:border-t-0">
      <span className="wire-sm text-muted pt-1">{stage.n}</span>

      <h3 className="text-base sm:text-lg font-bold">{stage.name}</h3>

      <div className="col-start-2 sm:col-start-3 mt-2 sm:mt-0">
        <div
          className="flex gap-[2px] h-6 items-end"
          role="img"
          aria-label={`${stage.name}: ${stage.count} items, ${stage.detail}`}
        >
          {Array.from({ length: SLOTS }, (_, i) => {
            const alive = i < stage.alive;
            return (
              <span
                key={i}
                className={`flex-1 origin-bottom ${
                  alive ? `${TONE_CLASS[stage.tone]} h-full` : "bg-rule h-1.5"
                }`}
                style={{
                  animation: "tick-settle 380ms cubic-bezier(0.22,1,0.36,1) both",
                  animationDelay: `${index * 90 + i * 4}ms`,
                }}
              />
            );
          })}
        </div>

        <div className="mt-2 flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className="font-[family-name:var(--font-wire)] text-sm font-semibold tabular-nums">
            {stage.count}
          </span>
          <span className="text-sm text-muted leading-snug">{stage.detail}</span>
        </div>
      </div>
    </li>
  );
}

export function Cascade() {
  return (
    <div>
      <ol className="list-none">
        {STAGES.map((stage, i) => (
          <Band key={stage.n} stage={stage} index={i} />
        ))}
      </ol>

      <p className="mt-5 pt-4 border-t border-rule text-sm text-muted max-w-prose">
        Solid ticks survived the stage. Faint ticks were dropped. Every number on
        this diagram is a setting you can change, and all of them are on the{" "}
        <a
          href="/console"
          className="text-ink underline decoration-signal decoration-2 underline-offset-4 hover:bg-signal/20"
        >
          console
        </a>
        .
      </p>
    </div>
  );
}
