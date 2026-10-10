import { useEffect, useMemo, useState } from "react";

import { ArticleImage } from "../components/ArticleImage";
import { Search } from "../components/Icons";
import { LibraryTabs } from "../components/LibraryTabs";
import { PersonaPicker } from "../components/PersonaPicker";
import { ReadAnyLink } from "../components/ReadAnyLink";
import { SourceMark } from "../components/SourceMark";
import { ERROR_COPY, StateView } from "../components/StateView";
import { ThemeToggle } from "../components/ThemeToggle";
import { Wordmark } from "../components/Wordmark";
import { api, errorKind, type ApiErrorKind, type ContentSummary } from "../lib/api";
import { DOMAINS, domainLabel, formatDate, plural, readingMinutes, sourceName } from "../lib/format";
import { AccountMenu } from "../components/AccountMenu";
import { useIsDemo } from "../lib/auth";
import { DEFAULT_PERSONA, parseDensity, personaOf, personaParam, readerPersona, type PersonaKey } from "../lib/personas";
import { navigate, withParams } from "../lib/router";

const SEARCH_DEBOUNCE_MS = 180;
const PAGE_SIZE = 24;
const SIDE_COUNT = 3;
const LEAD_WINDOW = 8;
const LEAD_MAX_TITLE = 100;

type Load = { status: "loading" } | { status: "ready"; items: ContentSummary[] } | { status: "error"; kind: ApiErrorKind };

export function LibraryPage({ url }: { url: URL }) {
  const q = url.searchParams.get("q") ?? "";
  const topic = url.searchParams.get("topic");
  const source = url.searchParams.get("source");
  const persona = readerPersona(url, useIsDemo());
  const density = parseDensity(url.searchParams.get("density"));
  const [draft, setDraft] = useState(q);
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [shown, setShown] = useState(PAGE_SIZE);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    document.title = "ReadLayer · Read anything. Understand it your way.";
  }, []);

  useEffect(() => {
    const t = setTimeout(() => {
      if (draft.trim() !== q) navigate(withParams(url, { q: draft.trim() || null }), { replace: true });
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [draft, q, url]);

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

  useEffect(() => setShown(PAGE_SIZE), [q, topic, source]);

  const sources = useMemo(() => {
    if (load.status !== "ready") return [];
    return [...new Set(load.items.map((i) => sourceName(i.site)))].sort((a, b) => a.localeCompare(b));
  }, [load]);

  // Only topics the library actually has (the taxonomy has 14; the corpus covers fewer).
  const topics = useMemo(() => {
    if (load.status !== "ready") return [];
    const present = new Set(load.items.map((i) => i.domain));
    return DOMAINS.filter((d) => present.has(d));
  }, [load]);

  const items = useMemo(() => {
    if (load.status !== "ready") return [];
    return load.items
      .filter((i) => (!topic || i.domain === topic) && (!source || sourceName(i.site) === source))
      // Newest first; within a day, the stories with the most that's new to this reader.
      .sort(
        (a, b) =>
          (b.published ?? "").slice(0, 10).localeCompare((a.published ?? "").slice(0, 10)) ||
          b.concepts_new - a.concepts_new ||
          a.title.localeCompare(b.title),
      );
  }, [load, topic, source]);

  const setParam = (key: string, value: string | null) => navigate(withParams(url, { [key]: value }), { replace: true });
  const readerHref = (id: string) =>
    withParams(new URL(`/read/${id}`, window.location.origin), {
      persona: personaParam(persona),
      density: url.searchParams.get("density"),
    });
  const filtered = Boolean(q || topic || source);
  // Lead: the first of the top few that has an image, a standfirst and a headline that fits.
  const leadIndex = Math.max(
    0,
    items
      .slice(0, LEAD_WINDOW)
      .findIndex((i) => i.image && i.description && i.title.length <= LEAD_MAX_TITLE),
  );
  const lead = items[leadIndex];
  const others = items.filter((_, i) => i !== leadIndex);
  const side = others.slice(0, SIDE_COUNT);
  const rest = others.slice(SIDE_COUNT);

  return (
    <>
      <a className="skip-link" href="#stories">
        Skip to articles
      </a>
      <header className="masthead">
        <div className="masthead__bar">
          <Wordmark size="lg" />
          <div className="masthead__tools">
            {persona && (
              <PersonaPicker value={persona} onChange={(k: PersonaKey) => setParam("persona", k === DEFAULT_PERSONA ? null : k)} />
            )}
            <ThemeToggle />
            <AccountMenu />
          </div>
        </div>
        <LibraryTabs current="library" persona={persona} />
        <div className="masthead__hero">
          <h1 className="masthead__tagline">
            Read anything. <em>Understand it your way.</em>
          </h1>
          <p className="masthead__lede">
            Writing on any subject with quiet notes, only on the ideas{" "}
            {persona ? (
              <>
                <span className="masthead__persona">{personaOf(persona).label.toLowerCase()}s</span> tend to miss.
              </>
            ) : (
              <>
                <span className="masthead__persona">you</span> are likely to miss.
              </>
            )}{" "}
            The author's words stay exactly as written.
          </p>
          <label className="search">
            <span className="visually-hidden">Search the library</span>
            <Search className="search__icon" />
            <input
              className="search__input"
              type="search"
              value={draft}
              placeholder="Search headlines and sources"
              onChange={(e) => setDraft(e.target.value)}
              autoComplete="off"
              spellCheck={false}
            />
          </label>
          <ReadAnyLink persona={persona} />
        </div>
      </header>

      <main className="library" id="stories" tabIndex={-1}>
        <div className="filters">
          <div className="filters__topics" role="group" aria-label="Filter by topic">
            <button type="button" className="filter" aria-pressed={!topic} onClick={() => setParam("topic", null)}>
              All topics
            </button>
            {topics.map((d) => (
              <button
                key={d}
                type="button"
                className="filter"
                aria-pressed={topic === d}
                onClick={() => setParam("topic", topic === d ? null : d)}
              >
                {domainLabel(d)}
              </button>
            ))}
          </div>
          <label className="filters__source">
            <span className="eyebrow">Source</span>
            <select value={source ?? ""} onChange={(e) => setParam("source", e.target.value || null)}>
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

        {load.status === "loading" && <LibrarySkeleton />}
        {load.status === "error" && (
          <StateView
            title={ERROR_COPY[load.kind].title}
            role="alert"
            actions={
              <button type="button" className="btn btn--primary" onClick={() => setAttempt((n) => n + 1)}>
                Try again
              </button>
            }
          >
            {ERROR_COPY[load.kind].body}
          </StateView>
        )}
        {load.status === "ready" && !lead && (
          <StateView
            title={filtered ? "Nothing matches that" : "The library is empty"}
            actions={
              filtered && (
                <button
                  type="button"
                  className="btn"
                  onClick={() => {
                    setDraft("");
                    navigate(withParams(url, { q: null, topic: null, source: null }), { replace: true });
                  }}
                >
                  Clear search and filters
                </button>
              )
            }
          >
            {filtered
              ? "Try a broader word, another topic, or all sources."
              : "Ingest a few articles and they will appear here."}
          </StateView>
        )}
        {lead && (
          <>
            <section className="front" aria-label="Top stories">
              <Story item={lead} href={readerHref(lead.id)} lead />
              {side.length > 0 && (
                <div className="front__side">
                  <h2 className="front__head eyebrow">Also new</h2>
                  <ul className="front__list">
                    {side.map((item) => (
                      <li key={item.id}>
                        <Story item={item} href={readerHref(item.id)} compact />
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </section>
            {rest.length > 0 && (
              <ul className="grid">
                {rest.slice(0, shown).map((item) => (
                  <li key={item.id}>
                    <Story item={item} href={readerHref(item.id)} />
                  </li>
                ))}
              </ul>
            )}
            {rest.length > shown && (
              <div className="library__more">
                <button type="button" className="btn" onClick={() => setShown((n) => n + PAGE_SIZE)}>
                  Show more · <span className="tnum">{rest.length - shown} left</span>
                </button>
              </div>
            )}
          </>
        )}
      </main>
    </>
  );
}

interface StoryProps {
  item: ContentSummary;
  href: string;
  lead?: boolean;
  compact?: boolean;
}

function Story({ item, href, lead = false, compact = false }: StoryProps) {
  const date = formatDate(item.published);
  const Heading = lead ? "h2" : "h3";
  const variant = lead ? " story--lead" : compact ? " story--compact" : "";
  return (
    <article className={`story${variant}`}>
      <ArticleImage
        src={item.image}
        site={item.site}
        domain={item.domain}
        width={lead ? 960 : compact ? 160 : 480}
        height={lead ? 540 : compact ? 120 : 270}
        priority={lead}
        className="story__media"
      />
      <div className="story__top">
        <SourceMark site={item.site} />
        {item.domain && <span className="story__topic eyebrow">{domainLabel(item.domain)}</span>}
      </div>
      <Heading className="story__title" title={compact ? item.title : undefined}>
        <a
          className="story__link"
          href={href}
          onClick={(e) => {
            if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
            e.preventDefault();
            navigate(href);
            window.scrollTo(0, 0);
          }}
        >
          {item.title}
        </a>
      </Heading>
      {item.description && !compact && <p className="story__standfirst">{item.description}</p>}
      <div className="story__meta">
        <span className="tnum">
          {readingMinutes(item.word_count)} min read{date && <> · {date}</>}
        </span>
        <NewBadge count={item.concepts_new} />
      </div>
    </article>
  );
}

function NewBadge({ count }: { count: number }) {
  if (count === 0) return <span className="badge badge--none">Nothing new to you</span>;
  return (
    <span className="badge">
      <span className="badge__mark" aria-hidden="true" />
      <span>
        <span className="tnum">{plural(count, "concept")}</span> new to you
      </span>
    </span>
  );
}

function LibrarySkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading the library">
      <div className="story story--lead story--skeleton">
        <div className="skeleton media" />
        <div className="skeleton" style={{ width: 160, height: 20 }} />
        <div className="skeleton sk-title" />
        <div className="skeleton sk-title" style={{ width: "60%" }} />
        <div className="skeleton sk-line" style={{ width: "80%" }} />
      </div>
      <ul className="grid">
        {Array.from({ length: 6 }, (_, i) => (
          <li key={i}>
            <div className="story story--skeleton">
              <div className="skeleton media" />
              <div className="skeleton" style={{ width: 120, height: 18 }} />
              <div className="skeleton sk-card-title" />
              <div className="skeleton sk-card-title" style={{ width: "70%" }} />
              <div className="skeleton sk-line" style={{ width: "90%" }} />
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
