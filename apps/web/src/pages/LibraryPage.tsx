import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";

import { Sidebar } from "../components/library/Sidebar";
import { LibraryRow } from "../components/library/libraryRows";
import { ERROR_COPY, StateView } from "../components/StateView";
import { TopBar } from "../components/TopBar";
import { api, errorKind, type ApiErrorKind, type ContentSummary } from "../lib/api";
import { useIsDemo } from "../lib/auth";
import { DOMAINS, domainLabel, plural, sourceName } from "../lib/format";
import { parseDensity, personaParam, readerPersona } from "../lib/personas";
import { parseTab, TABS, tabParam, type Tab } from "../lib/libraryTabs";
import { navigate, withParams } from "../lib/router";
import { savedApi } from "../lib/savedApi";

// For you and Saved are their own chunks; Topics (the corpus) stays in the main bundle.
const ForYouTab = lazy(() => import("../components/library/ForYouTab"));
const SavedTab = lazy(() => import("../components/library/SavedTab"));

const SEARCH_DEBOUNCE_MS = 180;
const PAGE_SIZE = 24;

type Load = { status: "loading" } | { status: "ready"; items: ContentSummary[] } | { status: "error"; kind: ApiErrorKind };


/** The library as a feed (Design pass C5): For you · Topics · Saved, with a sidebar. */
export function LibraryPage({ url }: { url: URL }) {
  const demo = useIsDemo();
  const persona = readerPersona(url, demo);
  const tab = parseTab(url);
  const q = url.searchParams.get("q") ?? "";
  const topic = url.searchParams.get("topic");
  const source = url.searchParams.get("source");
  const density = parseDensity(url.searchParams.get("density"));
  const [draft, setDraft] = useState(q);
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [shown, setShown] = useState(PAGE_SIZE);
  const [attempt, setAttempt] = useState(0);
  const [saved, setSaved] = useState<ContentSummary[] | null>(null);
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({});

  useEffect(() => {
    document.title = "Gloss · Read anything. Understand it your way.";
  }, []);

  const go = useCallback(
    (params: Record<string, string | null>) => {
      const base = url.pathname === "/for-you" ? new URL("/", window.location.origin + url.search) : url;
      navigate(withParams(base, params), { replace: true });
    },
    [url],
  );

  useEffect(() => {
    const t = setTimeout(() => {
      if (draft.trim() !== q) go({ q: draft.trim() || null, tab: draft.trim() ? "topics" : url.searchParams.get("tab") });
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [draft, q, go, url]);

  useEffect(() => {
    const ctrl = new AbortController();
    api
      .library(q, persona, density, ctrl.signal)
      .then((items) => setLoad({ status: "ready", items }))
      .catch((e: unknown) => {
        if (!ctrl.signal.aborted) setLoad({ status: "error", kind: errorKind(e) });
      });
    return () => ctrl.abort();
  }, [q, persona, density, attempt]);

  useEffect(() => {
    const ctrl = new AbortController();
    savedApi
      .list(persona, ctrl.signal)
      .then(setSaved)
      .catch(() => !ctrl.signal.aborted && setSaved([]));
    return () => ctrl.abort();
  }, [persona]);

  useEffect(() => setShown(PAGE_SIZE), [q, topic, source]);

  const savedIds = useMemo(() => new Set((saved ?? []).map((s) => s.id)), [saved]);
  const toggleSave = async (item: ContentSummary) => {
    const was = savedIds.has(item.id);
    setSaved((s) => (was ? (s ?? []).filter((x) => x.id !== item.id) : [item, ...(s ?? [])]));
    try {
      await (was ? savedApi.unsave(item.id, persona) : savedApi.save(item.id, persona));
    } catch {
      setSaved((s) => (was ? [item, ...(s ?? [])] : (s ?? []).filter((x) => x.id !== item.id)));
    }
  };

  const sources = useMemo(
    () => (load.status === "ready" ? [...new Set(load.items.map((i) => sourceName(i.site)))].sort((a, b) => a.localeCompare(b)) : []),
    [load],
  );
  const topics = useMemo(() => {
    if (load.status !== "ready") return [];
    const present = new Set(load.items.map((i) => i.domain));
    return DOMAINS.filter((d) => present.has(d));
  }, [load]);
  const items = useMemo(() => {
    if (load.status !== "ready") return [];
    return load.items
      .filter((i) => (!topic || i.domain === topic) && (!source || sourceName(i.site) === source))
      .sort(
        (a, b) =>
          (b.published ?? "").slice(0, 10).localeCompare((a.published ?? "").slice(0, 10)) ||
          b.concepts_new - a.concepts_new ||
          a.title.localeCompare(b.title),
      );
  }, [load, topic, source]);

  const readerHref = (id: string) =>
    withParams(new URL(`/read/${id}`, window.location.origin), {
      persona: personaParam(persona),
      density: url.searchParams.get("density"),
    });
  const selectTab = (t: Tab) => go({ tab: tabParam(t) });
  const onTabKey = (e: KeyboardEvent<HTMLButtonElement>, i: number) => {
    const step = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (!step) return;
    e.preventDefault();
    const next = TABS[(i + step + TABS.length) % TABS.length]?.id ?? "foryou";
    selectTab(next);
    tabRefs.current[next]?.focus();
  };
  const filtered = Boolean(q || topic || source);

  return (
    <>
      <a className="skip-link" href="#stories">
        Skip to articles
      </a>
      <TopBar url={url} search={{ value: draft, onChange: setDraft }} />
      <div className="feedwrap">
        <main className="feedmain" id="stories" tabIndex={-1}>
          <h1 className="visually-hidden">Gloss library</h1>
          <p className="feedmain__lede">
            Writing on any subject, with quiet notes in the margin only where you need them. The author's words stay
            exactly as written.
          </p>
          <div className="tabs" role="tablist" aria-label="Library">
            {TABS.map((t, i) => (
              <button
                key={t.id}
                ref={(el) => {
                  tabRefs.current[t.id] = el;
                }}
                type="button"
                role="tab"
                id={`tab-${t.id}`}
                aria-selected={tab === t.id}
                aria-controls={`panel-${t.id}`}
                tabIndex={tab === t.id ? 0 : -1}
                className="tabs__tab"
                onClick={() => selectTab(t.id)}
                onKeyDown={(e) => onTabKey(e, i)}
              >
                {t.label}
                {t.id === "saved" && saved && saved.length > 0 && <span className="tabs__count tnum">{saved.length}</span>}
              </button>
            ))}
          </div>

          <section id={`panel-${tab}`} role="tabpanel" aria-labelledby={`tab-${tab}`} className="panel">
            {tab === "foryou" && (
              <Suspense fallback={<p className="feedtab__note">Finding picks for you…</p>}>
                <ForYouTab persona={persona} />
              </Suspense>
            )}
            {tab === "saved" && (
              <Suspense fallback={<p className="feedtab__note">Loading your saved articles…</p>}>
                <SavedTab
                  items={saved}
                  href={readerHref}
                  onToggle={(id) => {
                    const item = saved?.find((s) => s.id === id);
                    if (item) void toggleSave(item);
                  }}
                />
              </Suspense>
            )}
            {tab === "topics" && (
              <>
                <div className="filters">
                  <div className="filters__topics" role="group" aria-label="Filter by topic">
                    <button type="button" className="filter" aria-pressed={!topic} onClick={() => go({ topic: null })}>
                      All topics
                    </button>
                    {topics.map((d) => (
                      <button key={d} type="button" className="filter" aria-pressed={topic === d} onClick={() => go({ topic: topic === d ? null : d })}>
                        {domainLabel(d)}
                      </button>
                    ))}
                  </div>
                  <label className="filters__source">
                    <span className="filters__label">Source</span>
                    <select value={source ?? ""} onChange={(e) => go({ source: e.target.value || null })}>
                      <option value="">All sources</option>
                      {sources.map((s) => (
                        <option key={s} value={s}>
                          {s}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                <p className="library__count" aria-live="polite">
                  {load.status === "ready" && (
                    <>
                      {plural(items.length, "article")}
                      {q && <> matching “{q}”</>} · newest first
                    </>
                  )}
                </p>
                {load.status === "loading" && <RowsSkeleton />}
                {load.status === "error" && (
                  <StateView
                    title={ERROR_COPY[load.kind].title}
                    role="alert"
                    margo="oops"
                    actions={
                      <button type="button" className="btn btn--primary" onClick={() => setAttempt((n) => n + 1)}>
                        Try again
                      </button>
                    }
                  >
                    {ERROR_COPY[load.kind].body}
                  </StateView>
                )}
                {load.status === "ready" && items.length === 0 && (
                  <StateView
                    title={filtered ? "Nothing matches that" : "The library is empty"}
                    margo="oops"
                    actions={
                      filtered && (
                        <button
                          type="button"
                          className="btn"
                          onClick={() => {
                            setDraft("");
                            go({ q: null, topic: null, source: null });
                          }}
                        >
                          Clear search and filters
                        </button>
                      )
                    }
                  >
                    {filtered ? "Try a broader word, another topic, or all sources." : "Paste any link to read it here."}
                  </StateView>
                )}
                <ul className="rows">
                  {items.slice(0, shown).map((item) => (
                    <li key={item.id}>
                      <LibraryRow item={item} href={readerHref(item.id)} saved={savedIds.has(item.id)} onSave={() => void toggleSave(item)} />
                    </li>
                  ))}
                </ul>
                {items.length > shown && (
                  <div className="library__more">
                    <button type="button" className="btn" onClick={() => setShown((n) => n + PAGE_SIZE)}>
                      Show more · <span className="tnum">{items.length - shown} left</span>
                    </button>
                  </div>
                )}
              </>
            )}
          </section>
        </main>
        <Sidebar persona={persona} demo={demo} topics={topics} settled={load.status !== "loading"} onTopic={(d) => go({ tab: "topics", topic: d })} />
      </div>
    </>
  );
}

function RowsSkeleton() {
  return (
    <ul className="rows" aria-busy="true" aria-label="Loading the library">
      {Array.from({ length: 5 }, (_, i) => (
        <li key={i}>
          <div className="row row--skeleton">
            <div className="row__body">
              <div className="skeleton" style={{ width: 140, height: 16 }} />
              <div className="skeleton sk-card-title" />
              <div className="skeleton sk-line" style={{ width: "80%" }} />
            </div>
            <div className="skeleton row__thumb" />
          </div>
        </li>
      ))}
    </ul>
  );
}
