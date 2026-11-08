/**
 * The NewsFramer mark.
 *
 * A dark navy tile carrying a photographer's finger frame: two thick amber
 * brackets at opposite corners, top left and bottom right, each with two arms
 * of about the same length. The frame is closed on those two corners and open
 * on the other two. A cream newspaper sits centred inside it: an outline page,
 * a solid masthead band with two knocked-out slots (headline and photo), and
 * two column lines. Owner locked this glyph (Option 1, primary cream) on
 * 2026-08-09, replacing the earlier camera.
 *
 * Drawn on a 512 grid. The brackets are 29 units thick and the page outline
 * is 16, which keeps the silhouette readable down to 24px, where the frame,
 * the masthead band and the column lines carry the identity.
 *
 * This geometry is duplicated in public/logo.svg and app/icon.svg. Change one,
 * change all three.
 */

const TILE = "#1E2430";
const AMBER = "#F0B429";
const CREAM = "#F2EDDF";

export function Logo({
  size = 32,
  className,
  title = "NewsFramer",
  decorative = false,
}: {
  size?: number;
  className?: string;
  title?: string;
  decorative?: boolean;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 512 512"
      className={className}
      role={decorative ? undefined : "img"}
      aria-label={decorative ? undefined : title}
      aria-hidden={decorative || undefined}
      focusable="false"
    >
      <rect width="512" height="512" rx="56" fill={TILE} />

      {/* the finger frame, rotationally symmetric about the centre */}
      <g
        fill="none"
        stroke={AMBER}
        strokeWidth="29"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M132 318V132H318" />
        <path d="M380 194V380H194" />
      </g>

      {/* the newspaper page, an outline so the tile reads through it */}
      <rect
        x="181"
        y="176"
        width="150"
        height="160"
        rx="20"
        fill="none"
        stroke={CREAM}
        strokeWidth="16"
      />

      {/* masthead band with two knocked-out slots */}
      <rect x="207" y="202" width="98" height="44" rx="10" fill={CREAM} />
      <rect x="219" y="215" width="42" height="18" rx="6" fill={TILE} />
      <rect x="271" y="215" width="22" height="18" rx="6" fill={TILE} />

      {/* two column lines */}
      <rect x="207" y="266" width="98" height="14" rx="7" fill={CREAM} />
      <rect x="207" y="292" width="70" height="14" rx="7" fill={CREAM} />
    </svg>
  );
}

/**
 * Mark plus wordmark. Every route's header uses this, so the lockup only has to
 * be spaced once. `tone` picks the wordmark colour for paper or ink grounds.
 */
export function LogoLockup({
  size = 30,
  tone = "paper",
  className,
}: {
  size?: number;
  tone?: "paper" | "ink";
  className?: string;
}) {
  return (
    <span className={`inline-flex items-center gap-2.5 ${className ?? ""}`}>
      <Logo size={size} decorative />
      <span
        className={`font-[family-name:var(--font-display)] text-lg font-bold tracking-[-0.03em] uppercase leading-none ${
          tone === "ink" ? "text-paper" : "text-ink"
        }`}
      >
        NewsFramer
      </span>
    </span>
  );
}
