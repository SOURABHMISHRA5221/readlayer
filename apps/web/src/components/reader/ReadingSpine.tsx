import { useEffect, useMemo, useRef, useState, type RefObject } from "react";

import { minutesLeft, placeInArticle, spineTicks, type SpineNote } from "../../lib/spine";

interface Props {
  /** The article's text column: the track is this, top to bottom. */
  article: RefObject<HTMLElement | null>;
  paragraphs: readonly { id: string; text: string }[];
  wordCount: number;
  /** The notes marked on the page; null until they have resolved. */
  notes: readonly SpineNote[] | null;
  hovered: string | null;
  active: string | null;
}

/**
 * The reader's left rail from 1280px (Wide layout, decision 45): how many notes, how long is
 * left, and a track of the whole article with a dot where each note sits and the part already
 * read filled in. Articles have no headings to list, so this is the "contents". The dots are a
 * picture only: the margin list and the highlights are the controls. A lazy chunk.
 */
export default function ReadingSpine({ article, paragraphs, wordCount, notes, hovered, active }: Props) {
  const fill = useRef<HTMLDivElement>(null);
  const [left, setLeft] = useState(() => minutesLeft(wordCount, 0));
  const ticks = useMemo(() => (notes ? spineTicks(notes, paragraphs) : []), [notes, paragraphs]);

  // The fill is written straight to the element, so scrolling never re-renders; the minutes
  // only change state when the whole number does.
  useEffect(() => {
    let frame = 0;
    const paint = () => {
      frame = 0;
      const el = article.current;
      if (!el || !fill.current) return;
      const rect = el.getBoundingClientRect();
      const atPageEnd = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2;
      const place = placeInArticle(rect.top, rect.height, window.innerHeight, atPageEnd);
      fill.current.style.transform = `scaleY(${place})`;
      setLeft(minutesLeft(wordCount, place));
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(paint);
    };
    paint();
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    return () => {
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      cancelAnimationFrame(frame);
    };
  }, [article, wordCount]);

  return (
    <aside className="spine" aria-label="Your place in this article">
      <div className="spine__in">
        {notes !== null && notes.length > 0 && (
          <p className="spine__stat spine__count">
            <strong className="tnum">{notes.length}</strong> {notes.length === 1 ? "note" : "notes"}
          </p>
        )}
        <p className="spine__stat spine__left">
          {left > 0 ? (
            <>
              <strong className="tnum">{left}</strong> min left
            </>
          ) : (
            "Finished"
          )}
        </p>
        <div className="spine__track" aria-hidden="true">
          <div className="spine__fill" ref={fill} />
          {ticks.map((t) => (
            <span
              key={t.id}
              className="spine__tick"
              data-id={t.id}
              data-level={t.level}
              data-linked={hovered === t.id || active === t.id || undefined}
              style={{ top: `${t.at * 100}%` }}
            />
          ))}
        </div>
      </div>
    </aside>
  );
}
