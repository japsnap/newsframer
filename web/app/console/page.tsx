import type { Metadata } from "next";
import { ConsoleClient } from "@/components/console/console-client";
import { SiteHeader, SiteFooter } from "@/components/site-chrome";

export const metadata: Metadata = {
  title: "Console · NewsFramer",
  description:
    "Interests, hypotheses, sources and every engine knob, on one working surface.",
};

export default function ConsolePage() {
  return (
    <div className="bg-ink text-paper min-h-full flex flex-col flex-1">
      <SiteHeader tone="ink" current="/console" />
      <main className="flex-1">
        <div className="shell pt-8">
          <p className="border-l-[3px] border-signal pl-4 text-muted-dark leading-relaxed max-w-[60ch]">
            <span className="text-paper font-semibold">
              NewsFramer has been paused since 26 September 2026.
            </span>{" "}
            The engine no longer runs, so a change saved here reaches no brief.
          </p>
        </div>
        <ConsoleClient />
      </main>
      <SiteFooter tone="ink" />
    </div>
  );
}
