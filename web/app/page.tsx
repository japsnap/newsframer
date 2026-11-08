import Link from "next/link";
import { SiteHeader, SiteFooter, REPO_URL } from "@/components/site-chrome";

/* Three themes from the real brief of 26 September 2026, the one published in
   the public repo as examples/brief-sample.md. Titles shortened, sources real. */
const SHEET = [
  {
    title: "Bitget loses $387M in a breach, North Korea suspected",
    sources: ["Decrypt", "Cointelegraph"],
    refs: "[1][2][3]",
  },
  {
    title: "Trump and Xi frame AI and trade as the core conflicts",
    sources: ["The Guardian", "Reuters", "Middle East Monitor"],
    refs: "[1][2][3][4]",
  },
  {
    title: "Anthropic and OpenAI ship new models within 90 minutes",
    sources: ["TechCrunch", "BleepingComputer"],
    refs: "[1][2]",
  },
];

/* The engine's real order of work, so the numbers mean something. */
const STEPS = [
  {
    title: "Read",
    body: "It pulls your RSS sources each morning.",
  },
  {
    title: "Clean",
    body: "Duplicates and noise are dropped.",
  },
  {
    title: "Score",
    body: "Each story is rated 0 to 10 against your topics.",
  },
  {
    title: "Write",
    body: "Claude writes one brief with every source cited, as Markdown and JSON.",
  },
];

export default function Home() {
  return (
    <>
      <SiteHeader current="/" />

      <main className="flex-1">
        {/* ---------- hero: also the wasaku.app card at 1200x750 ---------- */}
        <section className="shell pt-10 pb-14 md:pt-14 md:pb-16 lg:pb-24">
          <div className="grid gap-x-14 gap-y-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,27rem)] lg:items-center">
            <div>
              <h1 className="text-[length:var(--text-lead)] max-w-[15ch] anim-rise">
                Your morning news brief, written by Claude.
              </h1>

              <p
                className="mt-6 text-lg leading-relaxed max-w-[44ch] anim-rise"
                style={{ animationDelay: "60ms" }}
              >
                An open-source tool: Claude reads the sources you choose and writes one brief, every source cited.
              </p>

              <div
                className="mt-7 border-l-[3px] border-signal pl-4 max-w-[46ch] anim-rise"
                style={{ animationDelay: "120ms" }}
              >
                <p className="font-semibold">Paused since 26 September 2026.</p>
                <p className="text-muted leading-relaxed mt-0.5">
                  Claude and ChatGPT now do much of this in chat. The code stays open.
                </p>
              </div>

              <div
                className="mt-8 flex flex-wrap gap-3 anim-rise"
                style={{ animationDelay: "180ms" }}
              >
                <a href={REPO_URL} className="btn btn-ink">
                  View the code on GitHub
                </a>
                <Link href="/brief" className="btn btn-line">
                  Read a brief
                </Link>
              </div>
            </div>

            {/* the product itself: a slice of a real brief */}
            <figure className="anim-rise" style={{ animationDelay: "120ms" }}>
              <div className="bg-paper-2 border border-rule tick-rule">
                <div className="flex items-baseline justify-between gap-4 px-5 sm:px-6 pt-5 pb-4 border-b border-rule">
                  <p className="font-[family-name:var(--font-display)] font-bold text-lg tracking-[-0.02em]">
                    NewsFramer Briefing
                  </p>
                  <p className="text-sm text-muted tabular-nums shrink-0">
                    26 Sep 2026
                  </p>
                </div>

                <ol className="px-5 sm:px-6 py-1">
                  {SHEET.map((t, i) => (
                    <li
                      key={t.title}
                      className="py-4 border-b border-rule last:border-b-0 grid grid-cols-[1.5rem_minmax(0,1fr)] gap-x-3"
                    >
                      <span className="mt-0.5 h-6 w-6 bg-signal text-ink text-sm font-semibold grid place-items-center tabular-nums">
                        {i + 1}
                      </span>
                      <div>
                        <p className="font-[family-name:var(--font-display)] font-bold text-[1.05rem] leading-snug tracking-[-0.01em]">
                          {t.title}
                        </p>
                        <p className="text-sm text-muted mt-1">
                          {t.sources.join(", ")}{" "}
                          <span className="text-ink">{t.refs}</span>
                        </p>
                      </div>
                    </li>
                  ))}
                </ol>

                <p className="px-5 sm:px-6 py-4 border-t border-rule text-sm italic text-muted">
                  Built from 322 articles. 162 made the cutoff. 9 themes, 8
                  highlights.
                </p>
              </div>
              <figcaption className="sr-only">
                Three of the nine themes in the brief of 26 September 2026.
              </figcaption>
            </figure>
          </div>
        </section>

        {/* ---------- how it works ---------- */}
        <section className="shell py-16 md:py-20">
          <h2 className="text-[length:var(--text-section)]">How it works</h2>
          <ol className="mt-10 grid gap-x-8 gap-y-8 sm:grid-cols-2 lg:grid-cols-4">
            {STEPS.map((s, i) => (
              <li key={s.title} className="tick-rule pt-5">
                <p className="flex items-baseline gap-3">
                  <span className="text-muted tabular-nums">{i + 1}</span>
                  <span className="font-[family-name:var(--font-display)] font-bold text-xl">
                    {s.title}
                  </span>
                </p>
                <p className="mt-2 text-muted leading-relaxed">{s.body}</p>
              </li>
            ))}
          </ol>
        </section>

        {/* ---------- run your own ---------- */}
        <section className="bg-cream border-t border-rule py-14 md:py-16">
          <div className="shell grid gap-x-14 gap-y-6 md:grid-cols-[minmax(0,1fr)_auto] md:items-end">
            <div>
              <h2 className="text-[length:var(--text-section)]">
                Run your own
              </h2>
              <p className="mt-4 text-lg leading-relaxed max-w-[52ch]">
                One README that Claude Code can follow. You need Python 3.13, a Claude Pro or Max plan and a small Supabase project.
              </p>
            </div>
            <a href={REPO_URL} className="btn btn-ink justify-self-start">
              View the code on GitHub
            </a>
          </div>
        </section>
      </main>

      <SiteFooter />
    </>
  );
}
