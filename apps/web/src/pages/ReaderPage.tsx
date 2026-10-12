import type { CardAnnotation } from "@readlayer/annotator";
import { lazy, memo, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ArticleImage } from "../components/ArticleImage";
import { ConceptDrawer, ConceptRail } from "../components/ConceptRail";
import { Margo } from "../components/Margo";
import { ProgressBar } from "../components/ProgressBar";
import { ActionBar } from "../components/reader/ActionBar";
import { PrereadPath } from "../components/reader/PrereadPath";
import { Recap } from "../components/reader/Recap";
import { ERROR_COPY, StateView } from "../components/StateView";
import { TopBar } from "../components/TopBar";
import { sendRecEvent, UpNext } from "../components/UpNext";
import { useAnnotator } from "../hooks/useAnnotator";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { withoutPrompts } from "../lib/answers";
import { mergeRecapView, notesForView, type RecapView } from "../lib/recap";
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
import { DEFAULT_DENSITY, parseDensity, personaParam, readerPersona } from "../lib/personas";
import { navigate, withParams } from "../lib/router";
import { savedApi } from "../lib/savedApi";

type Load<T> = { status: "loading" } | { status: "ready"; data: T } | { status: "error"; kind: ApiErrorKind };
type Analysis = { status: "idle" } | { status: "running"; since: number } | { status: "failed"; message: string };

const RAIL_QUERY = "(min-width: 1200px)";
// The left rail (Wide layout, decision 45): its own chunk, loaded only where it is shown.
const SPINE_QUERY = "(min-width: 1280px)";
const ReadingSpine = lazy(() => import("../components/reader/ReadingSpine"));
// Two-phase "Open here": the server's analysis is cut off at 120 s; past this we stop waiting.
const ANALYSE_WINDOW_MS = 180_000;
const ANALYSE_RETRY_MS = 3000;
const ANALYSE_FAILED = "Notes are unavailable for this article; it's complete without them.";

const NO_LABELS: Readonly<Record<string, string>> = {};

export function ReaderPage({ id, url }: { id: string; url: URL }) {
  const persona = readerPersona(url, useIsDemo());
  const density = parseDensity(url.searchParams.get("density"));
  // Scoring internals on the card: dev builds only; the API also refuses outside ENV=dev.
  const debug = import.meta.env.DEV && url.searchParams.get("debug") === "1";
  const wide = useMediaQuery(RAIL_QUERY);
  const spine = useMediaQuery(SPINE_QUERY);

  const [content, setContent] = useState<Load<ContentDetail>>({ status: "loading" });
  const [notes, setNotes] = useState<Load<AnnotationsResponse>>({ status: "loading" });
  // The view (article|persona|density) the notes in `notes` were requested for (decision 46d).
  const [notesView, setNotesView] = useState<string | null>(null);
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
      .then((data) => {
        setNotes({ status: "ready", data });
        setNotesView(`${id}|${persona ?? ""}|${density}`);
      })
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
  // After a saved "Know this?" answer: the same request, quietly, so marks change in place (46d).
  // An open card stays open when its note is still in the new list (the annotator keeps it).
  const refreshNotes = useCallback(
    () =>
      api
        .annotations(id, persona, density, debug, undefined, true)
        .then((data) => {
          setNotes({ status: "ready", data: { ...data, extras: withoutPrompts(data.extras) } });
          setNotesView(`${id}|${persona ?? ""}|${density}`);
        }),
    [id, persona, density, debug],
  );
  const handle = useAnnotator(articleRef, article?.id ?? null, annotations, notesData?.extras ?? null, persona, refreshNotes);

  // Recap snapshot (Design pass A4): the bands of this page's noted concepts when the notes load,
  // taken once per view; a refetch after a "Know this?" answer only adds labels (decision 46d).
  const viewKey = `${id}|${persona ?? ""}|${density}`;
  const [view, setView] = useState<RecapView>({ key: "", labels: {} });
  useEffect(() => {
    const current = notesForView(notesData, notesView, viewKey);
    if (!current) return;
    setView((prev) => mergeRecapView(prev, viewKey, current.annotations, current.extras));
  }, [notesData, notesView, viewKey]);
  const labels = view.key === viewKey ? view.labels : NO_LABELS;
  const [snapshot, setSnapshot] = useState<Record<string, string> | null>(null);
  const snapshotFor = useRef<string | null>(null);
  useEffect(() => {
    setSnapshot(null);
    snapshotFor.current = null;
  }, [viewKey]);
  useEffect(() => {
    const ids = Object.keys(labels);
    if (!ids.length || snapshotFor.current === viewKey) return;
    snapshotFor.current = viewKey;
    api.bands(ids, persona).then(
      (b) => snapshotFor.current === viewKey && setSnapshot(b),
      () => {
        if (snapshotFor.current === viewKey) snapshotFor.current = null; // try again on the next notes
      },
    );
  }, [labels, viewKey, persona]);

  const [saved, setSaved] = useState(false);
  useEffect(() => {
    let live = true;
    savedApi.ids(persona).then((ids) => live && setSaved(ids.includes(id)), () => undefined);
    return () => {
      live = false;
    };
  }, [id, persona]);
  const toggleSave = async () => {
    const was = saved;
    setSaved(!was);
    try {
      await (was ? savedApi.unsave(id, persona) : savedApi.save(id, persona));
    } catch {
      setSaved(was);
    }
  };

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
      <TopBar url={url} />
      <main className="reader" ref={pageRef} id="article" tabIndex={-1}>
        <div className="readprogress">
          <ProgressBar target={pageRef} />
        </div>
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
            <ActionBar
              article={article}
              persona={persona}
              density={density}
              onDensity={(k) => setParam("density", k, DEFAULT_DENSITY)}
              saved={saved}
              onSave={() => void toggleSave()}
            />
            <ArticleFigure article={article} />
            {analysis.status === "running" && <PreparingNotice since={analysis.since} />}
            {analysis.status === "failed" && (
              <p className="reader__notice" role="status">
                <Margo mood="oops" size={28} />
                {analysis.message}
              </p>
            )}
            {notes.status === "error" && ready && (
              <p className="reader__notice" role="status">
                <Margo mood="oops" size={28} />
                Notes are unavailable right now; the article is complete without them.
              </p>
            )}
            {notesData?.preread && <PrereadPath item={notesData.preread} persona={persona} />}
            <div className="reader__body" ref={bodyRef}>
              {spine && (
                <Suspense fallback={null}>
                  <ReadingSpine
                    article={articleRef}
                    paragraphs={article.paragraphs}
                    wordCount={article.word_count}
                    notes={annotations && handle.resolved ? marked : null}
                    hovered={handle.hovered}
                    active={handle.active}
                  />
                </Suspense>
              )}
              <ArticleBody key={article.id} ref={articleRef} paragraphs={article.paragraphs} />
              {wide && annotations && handle.resolved && <ConceptRail items={marked} body={bodyRef} {...link} />}
            </div>
            {annotations && handle.resolved && (
              <div ref={endRef} className="reader__end">
                <Recap contentId={article.id} persona={persona} before={snapshot} labels={labels} answers={handle.answers} />
                <UpNext contentId={article.id} persona={persona} />
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
      <Margo mood="think" size={28} />
      Reading the article and preparing your notes… <span className="tnum">{seconds} s</span>
    </p>
  );
}

function ArticleHeader({ article }: { article: ContentDetail }) {
  const date = formatDate(article.published);
  const byline = formatByline(article.author);
  const kicker = domainLabel(article.domain);
  const source = sourceName(article.site);
  return (
    <header className="article-head">
      {kicker && <p className="article-head__kicker">{kicker}</p>}
      <h1 className="article-head__title">{article.title}</h1>
      {article.description && <p className="article-head__dek">{article.description}</p>}
      <div className="byline">
        <span className="byline__mark" aria-hidden="true">
          {(source.replace(/^the\s+/i, "")[0] ?? "?").toUpperCase()}
        </span>
        <div>
          <p className="byline__who">
            {source}
            {byline && <span className="byline__author"> · By {byline}</span>}
          </p>
          <p className="byline__when tnum">
            {readingMinutes(article.word_count)} min read
            {date && (
              <>
                {" · "}
                <time dateTime={article.published ?? undefined}>{date}</time>
              </>
            )}
          </p>
        </div>
      </div>
    </header>
  );
}

function ArticleFigure({ article }: { article: ContentDetail }) {
  if (!article.image) return null;
  return (
    <figure className="article-figure">
      <ArticleImage src={article.image} site={article.site} domain={article.domain} width={1360} height={765} priority />
      <figcaption>Image: {sourceName(article.site)}</figcaption>
    </figure>
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
