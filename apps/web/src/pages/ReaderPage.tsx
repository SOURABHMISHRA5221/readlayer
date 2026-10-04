import { memo, useEffect, useRef, useState } from "react";

import { Segmented } from "../components/Segmented";
import { SourceBadge } from "../components/SourceBadge";
import { useAnnotator } from "../hooks/useAnnotator";
import { api, errorMessage, type AnnotationsResponse, type ContentDetail } from "../lib/api";
import { formatCount, readingMinutes } from "../lib/format";
import { DENSITIES, PERSONAS, parseDensity, parsePersona } from "../lib/personas";
import { navigate, withParams } from "../lib/router";

type Load<T> = { status: "loading" } | { status: "ready"; data: T } | { status: "error"; message: string };

export function ReaderPage({ id, url }: { id: string; url: URL }) {
  const persona = parsePersona(url.searchParams.get("persona"));
  const density = parseDensity(url.searchParams.get("density"));
  // Scoring internals on the card: dev builds only, and the API also refuses outside ENV=dev.
  const debug = import.meta.env.DEV && url.searchParams.get("debug") === "1";

  const [content, setContent] = useState<Load<ContentDetail>>({ status: "loading" });
  const [notes, setNotes] = useState<Load<AnnotationsResponse>>({ status: "loading" });
  const articleRef = useRef<HTMLElement>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    setContent({ status: "loading" });
    api
      .content(id, ctrl.signal)
      .then((data) => {
        setContent({ status: "ready", data });
        document.title = `${data.title} · ReadLayer`;
      })
      .catch((e: unknown) => {
        if (!ctrl.signal.aborted) setContent({ status: "error", message: errorMessage(e) });
      });
    return () => ctrl.abort();
  }, [id]);

  useEffect(() => {
    const ctrl = new AbortController();
    api
      .annotations(id, persona, density, debug, ctrl.signal)
      .then((data) => setNotes({ status: "ready", data }))
      .catch((e: unknown) => {
        if (!ctrl.signal.aborted) setNotes({ status: "error", message: errorMessage(e) });
      });
    return () => ctrl.abort();
  }, [id, persona, density, debug]);

  const ready =
    content.status === "ready" && notes.status === "ready" && notes.data.content_id === id;
  const annotations = ready ? notes.data.annotations : null;
  const mounted = useAnnotator(articleRef, annotations);
  const shown = ready && mounted ? mounted.resolved : null;
  const personaInfo = PERSONAS.find((p) => p.key === persona);

  const setParam = (key: string, value: string, fallback: string) =>
    navigate(withParams(url, { [key]: value === fallback ? null : value }), { replace: true });

  return (
    <div className="reader">
      <header className="toolbar">
        <div className="toolbar__inner">
          <a
            className="toolbar__back"
            href="/"
            onClick={(e) => {
              if (e.metaKey || e.ctrlKey || e.button !== 0) return;
              e.preventDefault();
              navigate("/");
            }}
          >
            <span aria-hidden="true">←</span> Library
          </a>
          <Segmented
            label="Reading as"
            options={PERSONAS}
            value={persona}
            onChange={(k) => setParam("persona", k, "newcomer")}
          />
          <Segmented
            label="Notes"
            options={DENSITIES}
            value={density}
            onChange={(k) => setParam("density", k, "balanced")}
          />
          <p className="toolbar__count" aria-live="polite">
            {shown === null ? "…" : <><strong>{shown}</strong> {shown === 1 ? "note" : "notes"}</>}
            {debug && <span className="toolbar__debug">debug</span>}
          </p>
        </div>
        {personaInfo && <p className="toolbar__blurb">{personaInfo.blurb}</p>}
      </header>

      <main className="page">
        {content.status === "loading" && <p className="state">Fetching the article…</p>}
        {content.status === "error" && (
          <p className="state state--error" role="alert">
            {content.message}
          </p>
        )}
        {notes.status === "error" && (
          <p className="state state--error" role="alert">
            Annotations unavailable: {notes.message}
          </p>
        )}
        {content.status === "ready" && (
          <>
            <header className="article-head">
              <p className="article-head__kicker">
                <SourceBadge site={content.data.site} />
              </p>
              <h1 className="article-head__title">{content.data.title}</h1>
              <p className="article-head__meta">
                {formatCount(content.data.word_count)} words · {readingMinutes(content.data.word_count)} min read ·{" "}
                <a href={content.data.url} target="_blank" rel="noopener noreferrer">
                  Original<span className="visually-hidden"> (opens in a new tab)</span> ↗
                </a>
              </p>
              <p className="article-head__hint">
                Dotted underlines are notes for this reader. Hover, tap, or Tab to one and press Enter.
                Notes are ours; the text is the author's, unchanged.
              </p>
            </header>
            <ArticleBody key={content.data.id} ref={articleRef} paragraphs={content.data.paragraphs} />
          </>
        )}
      </main>
    </div>
  );
}

interface ArticleBodyProps {
  paragraphs: ContentDetail["paragraphs"];
  ref: React.Ref<HTMLElement>;
}

/** Never re-renders for a given article: the annotator owns the DOM inside it once mounted. */
const ArticleBody = memo(function ArticleBody({ paragraphs, ref }: ArticleBodyProps) {
  return (
    <article className="prose" ref={ref}>
      {paragraphs.map((p) => (
        <p key={p.id} data-rl-paragraph={p.id}>
          {p.text}
        </p>
      ))}
    </article>
  );
});
