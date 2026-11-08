import type { Metadata } from "next";
import { SiteHeader, SiteFooter, REPO_URL } from "@/components/site-chrome";
import { SAMPLE_BRIEF } from "@/lib/brief-sample";

export const metadata: Metadata = {
  title: "The brief · NewsFramer",
  description:
    "What a daily NewsFramer brief looks like: themes, hypothesis checks, what changed, investigations and highlights.",
};

const B = SAMPLE_BRIEF;

export default function BriefPage() {
  return (
    <>
      <SiteHeader current="/brief" />

      <main className="flex-1">
        <section className="shell pt-12 pb-8 md:pt-16">
          <div className="grid gap-x-14 gap-y-8 md:grid-cols-[minmax(0,1fr)_20rem] items-end">
            <div>
              <p className="wire text-muted">The output</p>
              <h1 className="mt-4 text-[length:var(--text-section)] max-w-[20ch]">
                What a brief looks like
              </h1>
              <p className="mt-4 text-lg max-w-[56ch] leading-relaxed">
                One brief each morning, built to a fixed format. Themes in title
                case, every fact traced to a numbered source, a hypothesis check
                wherever an article touches something you track, and a footer
                that says how much was left out.
              </p>
            </div>

            <div className="border border-signal bg-paper-2 px-5 py-4">
              <p className="wire-sm bg-signal text-ink inline-block px-2 py-1">
                Sample output
              </p>
              <p className="text-sm text-muted mt-2.5 leading-relaxed">
                The structure below is the real one. The story text is
                illustrative and is not reporting. Outlet names link to the
                publication's home page.
              </p>
              <a
                href={`${REPO_URL}/blob/main/examples/brief-sample.md`}
                className="inline-block text-sm mt-2.5 underline decoration-signal decoration-2 underline-offset-2"
              >
                Read a real brief from 26 September 2026
              </a>
            </div>
          </div>
        </section>

        {/* ---------- the brief sheet ---------- */}
        <section className="shell pb-20">
          <article className="bg-paper-2 border border-rule max-w-3xl mx-auto">
            <header className="border-b border-rule px-6 sm:px-10 py-7">
              <p className="wire-sm text-muted">{B.slot}</p>
              <h2 className="mt-3 text-3xl sm:text-4xl">
                NewsFramer Briefing
              </h2>
              <p className="wire mt-3 text-muted">{B.date}</p>
            </header>

            <div className="px-6 sm:px-10 py-8 grid gap-10">
              {B.themes.map((theme, ti) => (
                <section key={theme.title}>
                  <div className="flex items-baseline gap-3 mb-3">
                    <span className="wire-sm bg-signal text-ink shrink-0 px-1.5 py-0.5 tabular-nums">
                      {String(ti + 1).padStart(2, "0")}
                    </span>
                    <h3 className="text-[1.45rem] leading-tight">
                      {theme.title}
                    </h3>
                  </div>

                  {theme.paragraphs.map((p, i) => (
                    <p key={i} className="mb-3 leading-relaxed">
                      {p}
                    </p>
                  ))}

                  {theme.hypothesisCheck ? (
                    <p className="my-4 border-l-2 border-signal pl-4 text-[0.95rem] leading-relaxed">
                      <span className="font-semibold">Hypothesis check: </span>
                      {theme.hypothesisCheck.topic} (
                      {theme.hypothesisCheck.stance}): article [
                      {theme.hypothesisCheck.ref}]{" "}
                      <span
                        className={
                          theme.hypothesisCheck.verdict === "aligns with"
                            ? "font-semibold bg-signal text-ink px-1.5 py-0.5"
                            : "font-semibold bg-ink text-paper px-1.5 py-0.5"
                        }
                      >
                        {theme.hypothesisCheck.verdict}
                      </span>{" "}
                      this view.
                    </p>
                  ) : null}

                  {theme.coverageWarning ? (
                    <p className="my-4 border-l-2 border-signal pl-4 text-[0.9rem] italic text-ink">
                      ⚠ {theme.coverageWarning}
                    </p>
                  ) : null}

                  <p className="wire-sm text-muted mt-5 mb-2">Articles</p>
                  <ol className="text-[0.92rem] grid gap-1.5">
                    {theme.articles.map((a) => (
                      <li key={a.n} className="flex gap-2.5">
                        <span className="font-[family-name:var(--font-wire)] text-muted shrink-0">
                          [{a.n}]
                        </span>
                        <span>
                          {a.title}
                          {": "}
                          <a
                            href={a.url}
                            rel="noreferrer noopener"
                            target="_blank"
                            className="underline decoration-signal decoration-2 underline-offset-2 hover:bg-signal/20"
                          >
                            {a.source}
                          </a>
                        </span>
                      </li>
                    ))}
                  </ol>
                </section>
              ))}

              <p className="wire-sm text-muted border-y border-rule py-3 text-center">
                five further themes trimmed from this sample
              </p>

              {/* what changed */}
              <section>
                <h3 className="text-[1.35rem] mb-3">📈 What Changed</h3>
                <ul className="grid gap-2">
                  {B.whatChanged.map((w) => (
                    <li key={w.thread} className="text-[0.95rem]">
                      <span className="font-semibold">{w.thread}</span>
                      {": "}
                      <span className="font-[family-name:var(--font-wire)] text-sm">
                        {w.note}
                      </span>
                    </li>
                  ))}
                </ul>
                <p className="text-sm text-muted mt-3 leading-relaxed">
                  One tracked fact per running story, compared with the last
                  value the engine recorded. It never compares yesterday's
                  wording.
                </p>
              </section>

              {/* investigations */}
              <section>
                <h3 className="text-[1.35rem] mb-3">🔍 Investigations</h3>
                {B.investigations.map((d) => (
                  <p key={d.slug} className="text-[0.95rem] leading-relaxed">
                    {d.summary}{" "}
                    <a
                      href={d.url}
                      rel="noreferrer noopener"
                      target="_blank"
                      className="underline decoration-signal decoration-2 underline-offset-2 hover:bg-signal/20"
                    >
                      {d.source}
                    </a>
                  </p>
                ))}
              </section>

              {/* blindspot */}
              <section>
                <h3 className="text-[1.35rem] mb-3">🔦 Blindspot of the Day</h3>
                <p className="text-[0.95rem] leading-relaxed">
                  {B.blindspot.headline}
                </p>
                <p className="text-sm text-muted mt-1.5">{B.blindspot.note}</p>
              </section>

              {/* highlights */}
              <section>
                <h3 className="text-[1.35rem] mb-4">Highlights</h3>
                <ul className="grid gap-4">
                  {B.highlights.map((h) => (
                    <li key={h.title} className="text-[0.95rem] leading-relaxed">
                      <span className="font-semibold">{h.title}</span>:{" "}
                      {h.summary}{" "}
                      <a
                        href={h.url}
                        rel="noreferrer noopener"
                        target="_blank"
                        className="underline decoration-signal decoration-2 underline-offset-2 hover:bg-signal/20"
                      >
                        {h.source}
                      </a>
                    </li>
                  ))}
                </ul>
              </section>

              <footer className="border-t border-rule pt-5">
                <p className="text-sm italic text-muted leading-relaxed">
                  Briefing generated from {B.totals.fetched} articles.{" "}
                  {B.totals.passedCutoff} made the relevance cutoff.{" "}
                  {B.totals.themes} themes, {B.totals.highlights} highlights.
                </p>
              </footer>
            </div>
          </article>
        </section>

        {/* ---------- how the shape is set ---------- */}
        <section className="bg-ink text-paper py-16 md:py-20">
          <div className="shell">
            <h2 className="text-[length:var(--text-section)] max-w-[18ch]">
              Every part of that page is a setting
            </h2>
            <div className="mt-10 grid gap-x-12 md:grid-cols-2">
              {[
                {
                  k: "writer_min_relevance",
                  v: "6 / 10",
                  d: "The cutoff. Nothing under it reaches the page.",
                },
                {
                  k: "theme_count_multiplier",
                  v: "1.5",
                  d: "Nine themes today, because six bundles had something.",
                },
                {
                  k: "bundle_theme_cap",
                  v: "2",
                  d: "No bundle may take more than two themes.",
                },
                {
                  k: "writer_highlights_count",
                  v: "8",
                  d: "Strong single articles that did not join a theme.",
                },
                {
                  k: "surfaces.telegram.theme_size",
                  v: "S",
                  d: "About 800 characters of prose per theme.",
                },
                {
                  k: "blindspot_enabled",
                  v: "on",
                  d: "Turn it off and that section is simply gone.",
                },
              ].map((row) => (
                <div
                  key={row.k}
                  className="border-t border-rule-dark py-5 grid grid-cols-[minmax(0,1fr)_5rem] gap-4 items-baseline"
                >
                  <div>
                    <p className="font-[family-name:var(--font-wire)] text-[0.75rem] text-muted-dark break-all">
                      {row.k}
                    </p>
                    <p className="text-sm mt-1.5 text-muted-dark">{row.d}</p>
                  </div>
                  <p className="font-[family-name:var(--font-wire)] text-signal text-right tabular-nums">
                    {row.v}
                  </p>
                </div>
              ))}
            </div>
            <div className="mt-10">
              <a
                href={`${REPO_URL}#recipes`}
                className="wire inline-block bg-signal text-ink px-6 py-3.5 hover:bg-paper transition-colors"
              >
                See every setting on GitHub
              </a>
            </div>
          </div>
        </section>
      </main>

      <SiteFooter />
    </>
  );
}
