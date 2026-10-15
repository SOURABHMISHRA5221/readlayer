import { useLayoutEffect, useRef, useState } from "react";

import { Segmented } from "../../components/Segmented";
import { useMediaQuery } from "../../hooks/useMediaQuery";
import { CLAUSES, FORMATS, LENGTHS, LEVELS, SOURCE_TEXT, shape, type Format, type Length, type Level } from "./shapes";

const REDUCED = "(prefers-reduced-motion: reduce)";
const REFLOW_MS = 300;

/** The original sentence with each clause addressable, in the sentence's own order. */
function originalParts(): { text: string; id?: string }[] {
  const parts: { text: string; id?: string }[] = [];
  let from = 0;
  for (const c of CLAUSES) {
    const at = SOURCE_TEXT.indexOf(c.text, from);
    if (at < 0) continue;
    if (at > from) parts.push({ text: SOURCE_TEXT.slice(from, at) });
    parts.push({ text: c.text, id: c.id });
    from = at + c.text.length;
  }
  if (from < SOURCE_TEXT.length) parts.push({ text: SOURCE_TEXT.slice(from) });
  return parts;
}

const PARTS = originalParts();

/**
 * The /v2 concept's right panel (docs/plans/landing-v2.md): Length, Level and Format controls; the
 * original sentence and "Your shape", whose lines are the sentence's own clauses. A line keeps its
 * element across shapes (keyed by clause), so a change moves it (FLIP, 300 ms) instead of replacing
 * it. Hover, focus or a click on a line marks its clause in the original. Nothing here calls the app.
 */
export function ReshapeDemo() {
  const [length, setLength] = useState<Length>("full");
  const [level, setLevel] = useState<Level>("standard");
  const [format, setFormat] = useState<Format>("read");
  const [pinned, setPinned] = useState<string | null>(null);
  const [passing, setPassing] = useState<string | null>(null);
  const reduced = useMediaQuery(REDUCED);
  const lines = shape(length, level, format);
  const active = passing ?? pinned;

  const lineEls = useRef(new Map<string, HTMLElement>());
  const before = useRef<Map<string, DOMRect> | null>(null);
  const original = useRef<HTMLParagraphElement>(null);

  /** Remember where every line is, then change the shape. */
  const reshape = (apply: () => void) => {
    if (!reduced) {
      before.current = new Map([...lineEls.current].map(([id, el]) => [id, el.getBoundingClientRect()]));
    }
    apply();
  };

  useLayoutEffect(() => {
    const prev = before.current;
    before.current = null;
    if (!prev || reduced) return;
    for (const [id, el] of lineEls.current) {
      if (typeof el.animate !== "function") continue;
      const from = prev.get(id);
      const to = el.getBoundingClientRect();
      if (from) {
        const dx = from.left - to.left;
        const dy = from.top - to.top;
        if (dx || dy) el.animate([{ transform: `translate(${dx}px, ${dy}px)` }, { transform: "none" }], { duration: REFLOW_MS, easing: "ease-out" });
      } else {
        el.animate([{ opacity: 0 }, { opacity: 1 }], { duration: REFLOW_MS, easing: "ease-out" });
      }
    }
  }, [length, level, format, reduced]);

  // When the columns stack, bring the marked clause into view.
  useLayoutEffect(() => {
    if (!active) return;
    const mark = original.current?.querySelector<HTMLElement>(`[data-clause="${active}"]`);
    if (!mark || typeof mark.scrollIntoView !== "function") return;
    const r = mark.getBoundingClientRect();
    if (r.top < 0 || r.bottom > window.innerHeight) mark.scrollIntoView({ block: "nearest", behavior: reduced ? "auto" : "smooth" });
  }, [active, reduced]);

  return (
    <figure className="lp-demo lp2-demo">
      <div className="lp-demo__toggle lp2-controls">
        <Segmented label="Length" options={LENGTHS} value={length} onChange={(k) => reshape(() => setLength(k))} />
        <Segmented label="Level" options={LEVELS} value={level} onChange={(k) => reshape(() => setLevel(k))} />
        <Segmented label="Format" options={FORMATS} value={format} onChange={(k) => reshape(() => setFormat(k))} />
      </div>
      <div className="lp-demo__sheet">
        <p className="lp-demo__source">From The Economic Times · reshaped from the original · every line traces to its source</p>
        <div className="lp2-cols">
          <div className="lp2-col">
            <p className="lp2-col__head">Original</p>
            <p className="lp2-original" ref={original}>
              {PARTS.map((p, i) =>
                p.id ? (
                  <span key={i} data-clause={p.id} className={`lp2-clause${p.id === active ? " lp2-clause--on" : ""}`}>
                    {p.text}
                  </span>
                ) : (
                  p.text
                ),
              )}
            </p>
          </div>
          <div className="lp2-col">
            <p className="lp2-col__head">Your shape</p>
            <ul className={`lp2-shape lp2-shape--${format}`}>
              {lines.map((line) => (
                <li
                  key={line.id}
                  className="lp2-shape__item"
                  ref={(el) => {
                    if (el) lineEls.current.set(line.id, el);
                    else lineEls.current.delete(line.id);
                  }}
                >
                  <button
                    type="button"
                    className={`lp2-line${line.id === active ? " lp2-line--on" : ""}`}
                    aria-pressed={pinned === line.id}
                    onMouseEnter={() => setPassing(line.id)}
                    onMouseLeave={() => setPassing(null)}
                    onFocus={() => setPassing(line.id)}
                    onBlur={() => setPassing(null)}
                    onClick={() => setPinned((p) => (p === line.id ? null : line.id))}
                  >
                    <span className="lp2-line__tag">{line.tag}</span>
                    {line.at && <span className="lp2-line__at">▶ {line.at}</span>}
                    <span className="lp2-line__text">{line.text}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </div>
        <span className="btn btn--primary lp2-try">Try it on any article</span>
      </div>
    </figure>
  );
}
