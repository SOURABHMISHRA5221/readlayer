import type { CardAnnotation } from "@readlayer/annotator";
import { memo, useEffect, useMemo, useRef, useState } from "react";

import { ArticleImage } from "../components/ArticleImage";
import { ConceptDrawer, ConceptRail, EndBlock } from "../components/ConceptRail";
import { External } from "../components/Icons";
import { ReaderBar } from "../components/ReaderBar";
import { SourceMark } from "../components/SourceMark";
import { ERROR_COPY, StateView } from "../components/StateView";
import { useAnnotator } from "../hooks/useAnnotator";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { api, errorKind, type AnnotationsResponse, type ApiErrorKind, type ContentDetail } from "../lib/api";
import { domainLabel, formatByline, formatDate, readingMinutes, sourceName } from "../lib/format";
import { DEFAULT_DENSITY, DEFAULT_PERSONA, parseDensity, parsePersona } from "../lib/personas";
import { navigate, withParams } from "../lib/router";

type Load<T> = { status: "loading" } | { status: "ready"; data: T } | { status: "error"; kind: ApiErrorKind };

const RAIL_QUERY = "(min-width: 1200px)";

export function ReaderPage({ id, url }: { id: string; url: URL }) {
  const persona = parsePersona(url.searchParams.get("persona"));
  const density = parseDensity(url.searchParams.get("density"));
  // Scoring internals on the card: dev builds only; the API also refuses outside ENV=dev.
  const debug = import.meta.env.DEV && url.searchParams.get("debug") === "1";
  const wide = useMediaQuery(RAIL_QUERY);

  const [content, setContent] = useState<Load<ContentDetail>>({ status: "loading" });
  const [notes, setNotes] = useState<Load<AnnotationsResponse>>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  const articleRef = useRef<HTMLElement>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const pageRef = useRef<HTMLElement>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    setContent({ status: "loading" });
    api
      .content(id, ctrl.signal)
      .then((data) => setContent({ status: "ready", data }))
      .catch((e: unknown) => {
        if (!ctrl.signal.aborted) setContent({ status: "error", kind: errorKind(e) });
      });
    return () => ctrl.abort();
  }, [id, attempt]);

  useEffect(() => {
    const ctrl = new AbortController();
    api
      .annotations(id, persona, density, debug, ctrl.signal)
      .then((data) => setNotes({ status: "ready", data }))
      .catch((e: unknown) => {
        if (!ctrl.signal.aborted) setNotes({ status: "error", kind: errorKind(e) });
      });
    return () => ctrl.abort();
  }, [id, persona, density, debug, attempt]);

  useEffect(() => {
    document.title =
      content.status === "ready"
        ? `${content.data.title} · ReadLayer`
        : content.status === "error"
          ? `${ERROR_COPY[content.kind].title} · ReadLayer`
          : "ReadLayer";
  }, [content]);

  const article = content.status === "ready" ? content.data : null;
  const annotations =
    article && notes.status === "ready" && notes.data.content_id === id ? notes.data.annotations : null;
  const handle = useAnnotator(articleRef, article?.id ?? null, annotations);

  const marked = useMemo<CardAnnotation[]>(() => {
    if (!annotations || !handle.resolved) return [];
    const byId = new Map(annotations.map((a) => [a.id, a]));
    return handle.resolved.flatMap((rid) => byId.get(rid) ?? []);
  }, [annotations, handle.resolved]);

  const setParam = (key: string, value: string, fallback: string) =>
    navigate(withParams(url, { [key]: value === fallback ? null : value }), { replace: true });
  const libraryHref = withParams(new URL("/", window.location.origin), {
    persona: persona === DEFAULT_PERSONA ? null : persona,
  });
  const link = {
    hovered: handle.hovered,
    active: handle.active,
    onHighlight: handle.highlight,
    onOpen: handle.open,
  };

  return (
    <>
      <a className="skip-link" href="#article">
        Skip to article
      </a>
      <ReaderBar
        persona={persona}
        density={density}
        onPersona={(k) => setParam("persona", k, DEFAULT_PERSONA)}
        onDensity={(k) => setParam("density", k, DEFAULT_DENSITY)}
        libraryHref={libraryHref}
        article={pageRef}
        debug={debug}
      />
      <main className="reader" ref={pageRef} id="article" tabIndex={-1}>
        {content.status === "loading" && <ReaderSkeleton />}
        {content.status === "error" && (
          <div className="reader__state">
            <StateView
              title={ERROR_COPY[content.kind].title}
              role="alert"
              actions={
                <>
                  {content.kind !== "not_found" && (
                    <button type="button" className="btn btn--primary" onClick={() => setAttempt((n) => n + 1)}>
                      Try again
                    </button>
                  )}
                  <a
                    className="btn"
                    href={libraryHref}
                    onClick={(e) => {
                      e.preventDefault();
                      navigate(libraryHref);
                    }}
                  >
                    Back to the library
                  </a>
                </>
              }
            >
              {ERROR_COPY[content.kind].body}
            </StateView>
          </div>
        )}
        {article && (
          <div className="reader__grid">
            <ArticleHeader article={article} />
            {notes.status === "error" && (
              <p className="reader__notice" role="status">
                Notes are unavailable right now; the article is complete without them.
              </p>
            )}
            <div className="reader__body" ref={bodyRef}>
              <ArticleBody key={article.id} ref={articleRef} paragraphs={article.paragraphs} />
              {wide && annotations && handle.resolved && <ConceptRail items={marked} body={bodyRef} {...link} />}
            </div>
            {annotations && handle.resolved && <EndBlock items={marked} {...link} />}
          </div>
        )}
      </main>
      {!wide && <ConceptDrawer items={marked} {...link} />}
    </>
  );
}

function ArticleHeader({ article }: { article: ContentDetail }) {
  const date = formatDate(article.published);
  const byline = formatByline(article.author);
  const kicker = domainLabel(article.domain);
  return (
    <header className="article-head">
      <div className="article-head__source">
        <SourceMark site={article.site} />
        {date && (
          <>
            <span className="dot" aria-hidden="true" />
            <time dateTime={article.published ?? undefined}>{date}</time>
          </>
        )}
      </div>
      {kicker && <p className="article-head__kicker eyebrow">{kicker}</p>}
      <h1 className="article-head__title">{article.title}</h1>
      {article.description && <p className="article-head__standfirst">{article.description}</p>}
      <div className="article-head__meta">
        {byline && (
          <span className="article-head__byline">
            By <span>{byline}</span>
          </span>
        )}
        <span className="tnum">{readingMinutes(article.word_count)} min read</span>
        <a className="article-head__original" href={article.url} target="_blank" rel="noopener noreferrer">
          Read on {sourceName(article.site)}
          <External size={14} />
          <span className="visually-hidden"> (opens in a new tab)</span>
        </a>
      </div>
      {article.image && (
        <figure className="article-head__figure">
          <ArticleImage
            src={article.image}
            site={article.site}
            domain={article.domain}
            width={1320}
            height={743}
            priority
          />
          <figcaption>Image: {sourceName(article.site)}</figcaption>
        </figure>
      )}
    </header>
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

function ReaderSkeleton() {
  return (
    <div className="reader__grid" aria-busy="true" aria-label="Loading article">
      <div className="article-head">
        <div className="skeleton" style={{ width: 180, height: 20 }} />
        <div className="skeleton sk-title" />
        <div className="skeleton sk-title" style={{ width: "72%" }} />
        <div className="skeleton sk-line" style={{ width: "88%", marginTop: 20 }} />
        <div className="skeleton sk-line" style={{ width: "60%" }} />
      </div>
      <div className="reader__body">
        <div className="prose">
          {[96, 100, 92, 70, 0, 100, 94, 98, 56].map((w, i) =>
            w ? <div key={i} className="skeleton sk-text" style={{ width: `${w}%` }} /> : <div key={i} style={{ height: 24 }} />,
          )}
        </div>
      </div>
    </div>
  );
}
