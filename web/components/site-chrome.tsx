import Link from "next/link";
import { Logo, LogoLockup } from "@/components/Logo";

type Tone = "paper" | "ink";

/* The public engine repo. Never link newsframer-web: it is private and shows
   visitors a GitHub login page. */
export const REPO_URL = "https://github.com/japsnap/newsframer";

/* The console stays reachable at /console but is not promoted: the engine it
   edits is paused. */
const NAV = [
  { href: "/", label: "Overview" },
  { href: "/brief", label: "The brief" },
];

export function SiteHeader({
  tone = "paper",
  current,
}: {
  tone?: Tone;
  current?: string;
}) {
  const dark = tone === "ink";

  return (
    <header
      className={
        dark
          ? "border-b border-rule-dark bg-ink text-paper"
          : "border-b border-rule bg-paper text-ink"
      }
    >
      <div className="shell flex flex-wrap items-center gap-x-8 gap-y-3 py-4">
        <Link href="/" className="shrink-0" aria-label="NewsFramer, home">
          <LogoLockup tone={dark ? "ink" : "paper"} />
        </Link>

        <nav className="flex items-center gap-5 sm:gap-7 ml-auto">
          {NAV.map((item) => {
            const active = item.href === current;
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={`wire pb-0.5 border-b-2 transition-colors ${
                  active
                    ? "border-signal"
                    : `border-transparent ${dark ? "text-muted-dark hover:text-paper" : "text-muted hover:text-ink"}`
                }`}
              >
                {item.label}
              </Link>
            );
          })}
          <a
            href={REPO_URL}
            className={`wire pb-0.5 border-b-2 border-transparent transition-colors ${
              dark ? "text-muted-dark hover:text-paper" : "text-muted hover:text-ink"
            }`}
          >
            GitHub
          </a>
        </nav>
      </div>
    </header>
  );
}

export function SiteFooter({ tone = "paper" }: { tone?: Tone }) {
  const dark = tone === "ink";

  return (
    <footer
      className={`mt-auto ${
        dark
          ? "border-t border-rule-dark bg-ink text-muted-dark"
          : "border-t border-rule bg-paper-2 text-muted"
      }`}
    >
      <div className="shell py-8 flex flex-wrap items-center gap-x-8 gap-y-2">
        <span className="flex items-center gap-2">
          <Logo size={18} decorative />
          <span className="wire-sm">NewsFramer</span>
        </span>
        <span className="text-sm">
          Open source under the MIT licence. Paused since 26 September 2026.
        </span>
        <a
          href={REPO_URL}
          className={`wire-sm ml-auto border-b-2 border-signal pb-0.5 ${
            dark ? "text-paper" : "text-ink"
          }`}
        >
          Code on GitHub
        </a>
      </div>
    </footer>
  );
}
