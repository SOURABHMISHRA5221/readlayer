import type { CardAnnotation } from "@readlayer/annotator";
import { useState, type RefObject } from "react";

import { plural } from "../lib/format";
import type { PersonaKey } from "../lib/personas";
import { Margo } from "./Margo";
import { UpNext } from "./UpNext";

interface ConceptLinkProps {
  items: CardAnnotation[];
  hovered: string | null;
  active: string | null;
  onHighlight: (id: string | null) => void;
  onOpen: (id: string, focus: boolean) => void;
}

const LEVEL_TEXT = { new: "new to you", refresher: "a quick refresher" } as const;
const levelOf = (a: CardAnnotation) => ((a as { level?: string }).level === "refresher" ? "refresher" : "new");

/**
 * Margin (≥1200px): "N notes for you" as a short contents list, with Margo, until a note
 * opens; the open card is then set in this column as a sidenote, level with its line, and the
 * list steps aside (Design pass C6). The column keeps the class `rail`: the annotator measures it.
 */
export function ConceptRail({ items, ...link }: ConceptLinkProps & { body?: RefObject<HTMLElement | null> }) {
  const reading = link.active !== null;
  return (
    <aside className="rail" aria-label="Notes in this article" data-card-open={reading}>
      <div className="rail__toc" inert={reading}>
        <h2 className="rail__head">
          <Margo size={34} blink={!reading} />
          {plural(items.length, "note")} for you
        </h2>
        <p className="rail__sub">Pitched for what you already know. Tap a highlight or pick one here.</p>
        <ul className="rail__list">
          {items.map((a) => (
            <li key={a.id}>
              <button
                type="button"
                className="rail__item"
                data-level={levelOf(a)}
                data-linked={link.hovered === a.id}
                onPointerEnter={() => link.onHighlight(a.id)}
                onPointerLeave={() => link.onHighlight(null)}
                onFocus={() => link.onHighlight(a.id)}
                onBlur={() => link.onHighlight(null)}
                onClick={(e) => link.onOpen(a.id, e.detail === 0)}
              >
                <span className="rail__dot" aria-hidden="true" />
                {a.label}, {LEVEL_TEXT[levelOf(a)]}
              </button>
            </li>
          ))}
        </ul>
      </div>
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
        <span>{items.length === 1 ? "note" : "notes"} for you</span>
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
