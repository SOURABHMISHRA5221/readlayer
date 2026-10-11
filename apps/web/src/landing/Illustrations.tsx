import { useEffect, useRef, useState } from "react";

/**
 * The landing's small line drawings (plan A3): ink strokes, the note highlight in the accent,
 * always decorative. Colours come from classes in landing.css, so both themes work.
 */
const svgProps = { width: 96, height: 64, viewBox: "0 0 96 64", "aria-hidden": true, focusable: false } as const;

/** Jargon: a line of text with one word the reader skips past. */
export function JargonArt() {
  return (
    <svg className="lp-art" {...svgProps}>
      <path className="lp-art__line" d="M6 18h24M36 18h20M62 18h28M6 32h14" />
      <rect className="lp-art__hl" x="25" y="25" width="30" height="13" rx="3" />
      <path className="lp-art__ink" d="M27 39h26" />
      <path className="lp-art__line" d="M60 32h30M6 46h34M46 46h22" />
      <path className="lp-art__ink" d="M76 46q3-6 7-3t-2 7v2" />
      <circle className="lp-art__dot" cx="81" cy="56" r="1.6" />
    </svg>
  );
}

/** Looking it up: the article tab and a new one, and the reader's place lost. */
export function LookupArt() {
  return (
    <svg className="lp-art" {...svgProps}>
      <path className="lp-art__line" d="M6 14h22l3-6h16l3 6h40v44H6z" />
      <path className="lp-art__ink" d="M50 8h18l3 6" />
      <path className="lp-art__line" d="M14 26h40M14 36h52M14 46h28" />
      <circle className="lp-art__ink" cx="70" cy="44" r="7" fill="none" />
      <path className="lp-art__ink" d="M75 49l7 7" />
    </svg>
  );
}

/** Summaries: the author's long paragraph squeezed into two new lines. */
export function SummaryArt() {
  return (
    <svg className="lp-art" {...svgProps}>
      <path className="lp-art__line" d="M6 12h30M6 21h34M6 30h28M6 39h32M6 48h22" />
      <path className="lp-art__ink" d="M46 30h10m-4-4l4 4-4 4" />
      <path className="lp-art__ink" d="M64 24h26M64 34h18" />
      <path className="lp-art__hl-stroke" d="M86 12l1.5 3.5L91 17l-3.5 1.5L86 22l-1.5-3.5L81 17l3.5-1.5z" />
    </svg>
  );
}

/**
 * Step 4's small knowledge map: three nodes fill in once it scrolls into view, the page's one
 * orchestrated animation. Under reduced motion it is drawn filled, without moving.
 */
export function GrowingMap() {
  const ref = useRef<SVGSVGElement>(null);
  const [grown, setGrown] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (typeof IntersectionObserver === "undefined" || matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setGrown(true);
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setGrown(true);
          io.disconnect();
        }
      },
      { threshold: 0.6 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return (
    <svg
      ref={ref}
      className={`lp-map${grown ? " lp-map--grown" : ""}`}
      width="200"
      height="120"
      viewBox="0 0 200 120"
      aria-hidden="true"
      focusable="false"
    >
      <path className="lp-map__edge" d="M30 60L80 28M30 60L82 92M80 28L140 40M82 92L140 40M140 40L176 84M82 92L176 84" />
      <circle className="lp-map__node lp-map__node--known" cx="30" cy="60" r="9" />
      <circle className="lp-map__node lp-map__node--known" cx="80" cy="28" r="9" />
      <circle className="lp-map__node lp-map__node--grow" style={{ transitionDelay: "0ms" }} cx="82" cy="92" r="9" />
      <circle className="lp-map__node lp-map__node--grow" style={{ transitionDelay: "260ms" }} cx="140" cy="40" r="9" />
      <circle className="lp-map__node lp-map__node--grow" style={{ transitionDelay: "520ms" }} cx="176" cy="84" r="9" />
    </svg>
  );
}
