import { useEffect, useRef, useState } from "react";

import { api, type RecItem } from "../../lib/api";
import { flushEvents } from "../../lib/events";
import { personaParam, type PersonaKey } from "../../lib/personas";
import { BAND_LABEL, bandMoves, movesExcept, nextReads, type BandMove } from "../../lib/recap";
import { navigate, withParams } from "../../lib/router";
import { Margo } from "../Margo";

interface Props {
  contentId: string;
  persona: PersonaKey | null;
  /** Bands when the notes loaded (POST /v1/me/bands), and the labels to show. */
  before: Record<string, string> | null;
  labels: Record<string, string>;
  answers: ReadonlyMap<string, { label: string; known: boolean }>;
}

type Row = BandMove & { undone?: string };

/**
 * "What this article changed" (Design pass C6): band changes since the notes loaded, with Undo
 * (the opposite correction, so the row then shows the resulting band), the "Not really"
 * answers as next on the path, and up to two Up next items that teach them. Computed when the
 * reader reaches the end of the article.
 */
export function Recap({ contentId, persona, before, labels, answers }: Props) {
  const ref = useRef<HTMLElement>(null);
  const [rows, setRows] = useState<Row[] | null>(null);
  const [recs, setRecs] = useState<{ items: RecItem[]; teaches: boolean }>({ items: [], teaches: false });
  const unknown = [...answers].filter(([, a]) => !a.known);

  useEffect(() => {
    const el = ref.current;
    if (!el || !before) return;
    let done = false;
    const observer = new IntersectionObserver(async ([entry]) => {
      if (!entry?.isIntersecting || done) return;
      done = true;
      observer.disconnect();
      await flushEvents().catch(() => undefined); // a "Knew this" just before must count
      try {
        const now = await api.bands(Object.keys(before), persona);
        setRows(bandMoves(before, now, labels));
      } catch {
        setRows([]);
      }
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [before, labels, persona]);

  useEffect(() => {
    if (!unknown.length) return;
    const ctrl = new AbortController();
    api
      .recommendations(contentId, persona, null, ctrl.signal, "consumer") // the "Not really" terms
      .then((r) => setRecs(nextReads(r.items, new Set(unknown.map(([id]) => id)))))
      .catch(() => undefined);
    return () => ctrl.abort();
  }, [contentId, persona, unknown.length]);

  const undo = async (row: Row) => {
    try {
      const res = await api.correct(row.conceptId, !row.up, persona);
      setRows((rs) => (rs ?? []).map((r) => (r.conceptId === row.conceptId ? { ...r, undone: res.band } : r)));
    } catch {
      /* the row stays as it was; the reader can try again */
    }
  };

  // Only "Not really" answers get their own row; a "Yes" stays a band move with its Undo.
  const moves = movesExcept(rows ?? [], new Set(unknown.map(([id]) => id)));
  const nothing = rows !== null && !moves.length && !unknown.length;
  return (
    <section className="recap" ref={ref} aria-labelledby="recap-h">
      <div className="recap__head">
        <Margo mood="happy" size={52} />
        <h2 id="recap-h">What this article changed</h2>
      </div>
      <p className="recap__lede" aria-live="polite">
        {rows === null
          ? "Your map updates as you consume content."
          : nothing
            ? "Nothing moved on your map this time. Open a note or answer a Know this? and it will."
            : "Your map updated as you consumed this. Undo anything that looks wrong."}
      </p>
      {(moves.length > 0 || unknown.length > 0) && (
        <ul className="recap__moves">
          {moves.map((m) => (
            <li key={m.conceptId}>
              <div>
                <b>{m.label}</b>
                <small>{m.undone ? `Undone: now ${BAND_LABEL[m.undone] ?? m.undone}` : m.up ? "You learned something here" : "Marked as less familiar"}</small>
              </div>
              <span className="recap__mv">
                <i data-band={m.from} aria-hidden="true" />
                {BAND_LABEL[m.from]}
                <span className="recap__arrow" aria-hidden="true" />
                <i data-band={m.to} aria-hidden="true" />
                {BAND_LABEL[m.to]}
              </span>
              {!m.undone && (
                <button type="button" className="btn btn--sm" aria-label={`Undo the change to ${m.label}`} onClick={() => void undo(m)}>
                  Undo
                </button>
              )}
            </li>
          ))}
          {unknown.map(([id, a]) => (
            <li key={id}>
              <div>
                <b>{a.label}</b>
                <small>You said "Not really", so it's next on your path</small>
              </div>
              <span className="recap__mv">
                <i data-band="next" aria-hidden="true" />
                Next on your path
              </span>
            </li>
          ))}
        </ul>
      )}
      {recs.items.length > 0 && (
        <div className="recap__next">
          {recs.items.map((r) => {
            const taught = r.triggers.find((t) => unknown.some(([id]) => id === t.id));
            const href = r.content_id
              ? withParams(new URL(`/read/${r.content_id}`, window.location.origin), { persona: personaParam(persona) })
              : r.url;
            return (
              <a
                key={r.id}
                className="recap__card"
                href={href}
                target={r.content_id ? undefined : "_blank"}
                rel={r.content_id ? undefined : "noopener noreferrer"}
                onClick={(e) => {
                  if (!r.content_id || e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
                  e.preventDefault();
                  navigate(href);
                  window.scrollTo(0, 0);
                }}
              >
                <p className="recap__k">
                  {r.format === "video" ? "Watch" : r.format === "podcast" ? "Listen" : "Read next"}
                  {recs.teaches && taught ? `, teaches ${taught.label}` : ""}
                </p>
                <p className="recap__t">{r.title}</p>
                <p className="recap__w">{r.source}</p>
              </a>
            );
          })}
        </div>
      )}
    </section>
  );
}
