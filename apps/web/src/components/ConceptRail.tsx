import type { CardAnnotation } from "@readlayer/annotator";
import { useLayoutEffect, useRef, useState, type RefObject } from "react";

import { plural } from "../lib/format";
import type { PersonaKey } from "../lib/personas";
import { UpNext } from "./UpNext";

interface ConceptLinkProps {
  items: CardAnnotation[];
  hovered: string | null;
  active: string | null;
  onHighlight: (id: string | null) => void;
  onOpen: (id: string, focus: boolean) => void;
}

const HEAD_PX = 28;
const LINE_PX = 26; // a mark's box height at body size
const CHIP_PX = 30;
const GAP_PX = 6;

/**
 * Margin rail (≥1200px): each concept chip sits level with its paragraph. Positions are
 * measured from the rendered article and re-measured when it resizes (fonts, viewport).
 */
export function ConceptRail({ items, body, ...link }: ConceptLinkProps & { body: RefObject<HTMLElement | null> }) {
  const [tops, setTops] = useState<number[]>([]);
  const listRef = useRef<HTMLUListElement>(null);

  useLayoutEffect(() => {
    const container = body.current;
    const list = listRef.current;
    if (!container || !list) return;
    const measure = () => {
      const origin = list.getBoundingClientRect().top;
      let floor = HEAD_PX + GAP_PX;
      setTops(
        items.map((a) => {
          // Level with the note's own line; its paragraph if the mark isn't in the DOM yet.
          const anchor =
            container.querySelector<HTMLElement>(`.rl-mark[data-rl-id="${CSS.escape(a.id)}"]`) ??
            container.querySelector<HTMLElement>(`[data-rl-paragraph="${CSS.escape(a.paragraph_id)}"]`);
          const lineTop = anchor ? anchor.getBoundingClientRect().top - origin : floor;
          const top = Math.max(lineTop - (CHIP_PX - LINE_PX) / 2, floor);
          floor = top + CHIP_PX + GAP_PX;
          return top;
        }),
      );
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(container);
    return () => observer.disconnect();
  }, [items, body]);

  return (
    // An open card is set over this column as a sidenote: the other chips step back.
    <aside className="rail" aria-label="Concepts in this article" data-card-open={link.active !== null}>
      <p className="rail__head eyebrow">{plural(items.length, "concept")} for you</p>
      <ul className="rail__list" ref={listRef}>
        {items.map((a, i) => (
          <li key={a.id} className="rail__item" style={{ transform: `translateY(${tops[i] ?? 0}px)` }}>
            <ConceptChip annotation={a} {...link} />
          </li>
        ))}
      </ul>
    </aside>
  );
}

export function ConceptChip({
  annotation,
  hovered,
  active,
  onHighlight,
  onOpen,
}: Omit<ConceptLinkProps, "items"> & { annotation: CardAnnotation }) {
  return (
    <button
      type="button"
      className="chip"
      data-linked={hovered === annotation.id}
      aria-current={active === annotation.id}
      onPointerEnter={() => onHighlight(annotation.id)}
      onPointerLeave={() => onHighlight(null)}
      onFocus={() => onHighlight(annotation.id)}
      onBlur={() => onHighlight(null)}
      onClick={(e) => onOpen(annotation.id, e.detail === 0)}
    >
      <span className="chip__dot" aria-hidden="true" />
      <span className="chip__text">{annotation.label}</span>
    </button>
  );
}

/** Below 1200px: the same concepts behind a bottom "N concepts for you" drawer. */
export function ConceptDrawer({ items, hidden: tucked = false, ...link }: ConceptLinkProps & { hidden?: boolean }) {
  const [open, setOpen] = useState(false);
  if (!items.length) return null;
  const hidden = tucked || link.active !== null;
  return (
    <div className="drawer" data-open={open} data-hidden={hidden} inert={hidden}>
      <button
        type="button"
        className="drawer__toggle"
        aria-expanded={open}
        aria-controls="concept-drawer"
        onClick={() => setOpen((v) => !v)}
        onKeyDown={(e) => {
          if (e.key === "Escape") setOpen(false);
        }}
      >
        <span className="drawer__count tnum">{items.length}</span>
        <span>{items.length === 1 ? "concept" : "concepts"} for you</span>
        <span className="drawer__caret" aria-hidden="true" />
      </button>
      <div
        id="concept-drawer"
        className="drawer__panel"
        hidden={!open}
        onKeyDown={(e) => {
          if (e.key === "Escape") setOpen(false);
        }}
      >
        <ul className="drawer__list">
          {items.map((a) => (
            <li key={a.id}>
              <ConceptChip
                annotation={a}
                {...link}
                onOpen={(id, focus) => {
                  setOpen(false);
                  link.onOpen(id, focus);
                }}
              />
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

export function EndBlock({ items, contentId, persona, ...link }: ConceptLinkProps & { contentId: string; persona: PersonaKey | null }) {
  return (
    <section className="end" aria-labelledby="end-title">
      <div className="end__met">
        <p className="eyebrow">Before you go</p>
        <h2 id="end-title" className="end__title">
          {items.length ? (
            <>
              You met <span className="tnum">{plural(items.length, "new concept")}</span>
            </>
          ) : (
            "Nothing here was new to you"
          )}
        </h2>
        {items.length > 0 && (
          <ul className="end__chips">
            {items.map((a) => (
              <li key={a.id}>
                <ConceptChip annotation={a} {...link} />
              </li>
            ))}
          </ul>
        )}
      </div>
      <UpNext contentId={contentId} persona={persona} />
    </section>
  );
}
