import { renderPreread, type CardAnnotation, type PrereadAnnotation } from "@readlayer/annotator";
import { memo, useEffect, useMemo, useRef, useState } from "react";

import { ArticleImage } from "../components/ArticleImage";
import { ConceptDrawer, ConceptRail, EndBlock } from "../components/ConceptRail";
import { External } from "../components/Icons";
import { ReaderBar } from "../components/ReaderBar";
import { sendRecEvent } from "../components/UpNext";
import { SourceMark } from "../components/SourceMark";
import { ERROR_COPY, StateView } from "../components/StateView";
import { useAnnotator } from "../hooks/useAnnotator";
import { useMediaQuery } from "../hooks/useMediaQuery";
import {
  api,
  ApiError,
  errorKind,
  type AnnotationsResponse,
  type ApiErrorKind,
  type ContentDetail,
} from "../lib/api";
import { domainLabel, formatByline, formatDate, readingMinutes, sourceName } from "../lib/format";
import { useIsDemo } from "../lib/auth";
import {
  DEFAULT_DENSITY,
  DEFAULT_PERSONA,
  parseDensity,
  personaParam,
  readerPersona,
  type PersonaKey,
} from "../lib/personas";
import { navigate, withParams } from "../lib/router";

type Load<T> = { status: "loading" } | { status: "ready"; data: T } | { status: "error"; kind: ApiErrorKind };
type Analysis = { status: "idle" } | { status: "running"; since: number } | { status: "failed"; message: string };

const RAIL_QUERY = "(min-width: 1200px)";
// Two-phase "Open here": the server's analysis is cut off at 120 s; past this we stop waiting.
const ANALYSE_WINDOW_MS = 180_000;
const ANALYSE_RETRY_MS = 3000;
const ANALYSE_FAILED = "Notes are unavailable for this article; it's complete without them.";

export function ReaderPage({ id, url }: { id: string; url: URL }) {
  const persona = readerPersona(url, useIsDemo());
  const density = parseDensity(url.searchParams.get("density"));
  // Scoring internals on the card: dev builds only; the API also refuses outside ENV=dev.
  const debug = import.meta.env.DEV && url.searchParams.get("debug") === "1";
  const wide = useMediaQuery(RAIL_QUERY);

  const [content, setContent] = useState<Load<ContentDetail>>({ status: "loading" });
  const [notes, setNotes] = useState<Load<AnnotationsResponse>>({ status: "loading" });
  const [analysis, setAnalysis] = useState<Analysis>({ status: "idle" });
  const [attempt, setAttempt] = useState(0);
  const articleRef = useRef<HTMLElement>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const pageRef = useRef<HTMLElement>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const recId = url.searchParams.get("rec");
  const [endVisible, setEndVisible] = useState(false);

  // The end block lists the same concepts, so the floating drawer steps aside there.
  useEffect(() => {
    const el = endRef.current;
    if (!el) return;
    const observer = new IntersectionObserver(([entry]) => setEndVisible(!!entry?.isIntersecting));
    observer.observe(el);
    return () => observer.disconnect();
  });
  const completedRef = useRef<string | null>(null);

  // A recommended library article read to the end counts as a completion for ranking (once).
  useEffect(() => {
    const el = endRef.current;
    if (!recId || !el || completedRef.current === recId) return;
    const observer = new IntersectionObserver(([entry]) => {
      if (entry?.isIntersecting && completedRef.current !== recId) {
        completedRef.current = recId;
        sendRecEvent(persona, "rec_completed", recId);
        observer.disconnect();
      }
    });
    observer.observe(el);
    return () => observer.disconnect();
  });

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

  // A missing status (older API) means ready.
  const analysing = content.status === "ready" && content.data.status === "analysing";
  const ready = content.status === "ready" && !analysing;

  // Phase 2: the article is on screen; ask the API to analyse it, then let the notes ink in.
  useEffect(() => {
    if (!analysing) return;
    const ctrl = new AbortController();
    const since = Date.now();
    setAnalysis({ status: "running", since });
    void (async () => {
      while (!ctrl.signal.aborted && Date.now() - since < ANALYSE_WINDOW_MS) {
        try {
          if ((await api.analyse(id, ctrl.signal)) === "ready") {
            setAnalysis({ status: "idle" });
            setContent((c) => (c.status === "ready" ? { status: "ready", data: { ...c.data, status: "ready" } } : c));
            return;
          }
        } catch (e: unknown) {
          if (ctrl.signal.aborted) return;
          setAnalysis({ status: "failed", message: e instanceof ApiError && e.detail ? e.detail : ANALYSE_FAILED });
          return;
        }
        await new Promise((r) => setTimeout(r, ANALYSE_RETRY_MS));
      }
      if (!ctrl.signal.aborted) setAnalysis({ status: "failed", message: ANALYSE_FAILED });
    })();
    return () => ctrl.abort();
  }, [id, analysing]);

  useEffect(() => {
    if (!ready) return;
    const ctrl = new AbortController();
    api
      .annotations(id, persona, density, debug, ctrl.signal)
      .then((data) => setNotes({ status: "ready", data }))
      .catch((e: unknown) => {
        if (!ctrl.signal.aborted) setNotes({ status: "error", kind: errorKind(e) });
      });
    return () => ctrl.abort();
  }, [id, persona, density, debug, attempt, ready]);

  useEffect(() => {
    document.title =
      content.status === "ready"
        ? `${content.data.title} · Gloss`
        : content.status === "error"
          ? `${ERROR_COPY[content.kind].title} · Gloss`
          : "Gloss";
  }, [content]);

  const article = content.status === "ready" ? content.data : null;
  const notesData = article && notes.status === "ready" && notes.data.content_id === id ? notes.data : null;
  const annotations = notesData?.annotations ?? null;
  const handle = useAnnotator(articleRef, article?.id ?? null, annotations, notesData?.extras ?? null, persona);

  const marked = useMemo<CardAnnotation[]>(() => {
    if (!annotations || !handle.resolved) return [];
    const byId = new Map(annotations.map((a) => [a.id, a]));
    return handle.resolved.flatMap((rid) => byId.get(rid) ?? []);
  }, [annotations, handle.resolved]);

  const setParam = (key: string, value: string, fallback: string) =>
    navigate(withParams(url, { [key]: value === fallback ? null : value }), { replace: true });
  const libraryHref = withParams(new URL("/", window.location.origin), { persona: personaParam(persona) });
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
            {analysis.status === "running" && <PreparingNotice since={analysis.since} />}
            {analysis.status === "failed" && (
              <p className="reader__notice" role="status">
                {analysis.message}
              </p>
            )}
            {notes.status === "error" && ready && (
              <p className="reader__notice" role="status">
                Notes are unavailable right now; the article is complete without them.
              </p>
            )}
            {notesData?.preread && <PrereadCard item={notesData.preread} persona={persona} />}
            <div className="reader__body" ref={bodyRef}>
              <ArticleBody key={article.id} ref={articleRef} paragraphs={article.paragraphs} />
              {wide && annotations && handle.resolved && <ConceptRail items={marked} body={bodyRef} {...link} />}
            </div>
            {annotations && handle.resolved && (
              <div ref={endRef}>
                <EndBlock items={marked} contentId={article.id} persona={persona} {...link} />
              </div>
            )}
          </div>
        )}
      </main>
      {!wide && <ConceptDrawer items={marked} hidden={endVisible} {...link} />}
    </>
  );
}

/** Phase 2 in progress: the article is readable; say what's coming and how long it's been. */
function PreparingNotice({ since }: { since: number }) {
  const [, tick] = useState(0);
  useEffect(() => {
    const t = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, []);
  const seconds = Math.round((Date.now() - since) / 1000);
  return (
    <p className="reader__notice reader__notice--working" role="status">
      <span className="reader__pulse" aria-hidden="true" />
      Preparing your notes… <span className="tnum">{seconds} s</span>
    </p>
  );
}

/** The pre-read card (DESIGN §6.4), drawn by the annotator package so the extension shares it. */
function PrereadCard({ item, persona }: { item: PrereadAnnotation; persona: PersonaKey | null }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const href = (contentId: string) =>
      withParams(new URL(`/read/${contentId}`, window.location.origin), { persona: personaParam(persona) });
    const handle = renderPreread(el, item, {
      href: (step) => href(step.content_id ?? ""),
      onOpen: (step, e) => {
        if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || !step.content_id) return;
        e.preventDefault();
        navigate(href(step.content_id));
        window.scrollTo(0, 0);
      },
    });
    return () => handle.destroy();
  }, [item, persona]);
  return <div ref={ref} className="reader__preread" />;
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
