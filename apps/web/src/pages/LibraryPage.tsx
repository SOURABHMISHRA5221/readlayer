import { useEffect, useState } from "react";

import { SourceBadge } from "../components/SourceBadge";
import { api, errorMessage, type ContentSummary } from "../lib/api";
import { formatCount, readingMinutes } from "../lib/format";
import { navigate, withParams } from "../lib/router";

const SEARCH_DEBOUNCE_MS = 180;

type Load =
  | { status: "loading" }
  | { status: "ready"; items: ContentSummary[] }
  | { status: "error"; message: string };

export function LibraryPage({ url }: { url: URL }) {
  const q = url.searchParams.get("q") ?? "";
  const [draft, setDraft] = useState(q);
  const [load, setLoad] = useState<Load>({ status: "loading" });

  useEffect(() => {
    const t = setTimeout(() => {
      if (draft !== q) navigate(withParams(url, { q: draft.trim() || null }), { replace: true });
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [draft, q, url]);

  useEffect(() => {
    const ctrl = new AbortController();
    api
      .library(q, ctrl.signal)
      .then((items) => setLoad({ status: "ready", items }))
      .catch((e: unknown) => {
        if (!ctrl.signal.aborted) setLoad({ status: "error", message: errorMessage(e) });
      });
    return () => ctrl.abort();
  }, [q]);

  return (
    <div className="library">
      <header className="masthead">
        <p className="masthead__kicker">A personal reading layer</p>
        <h1 className="masthead__title">
          Read<em>Layer</em>
        </h1>
        <p className="masthead__lede">
          Business and economy writing, annotated only where <em>you</em> are likely to need it. The
          author's words stay exactly as written.
        </p>
        <label className="search">
          <span className="search__label">Search the library</span>
          <input
            className="search__input"
            type="search"
            value={draft}
            placeholder="Title or source — try “inflation”"
            onChange={(e) => setDraft(e.target.value)}
            autoComplete="off"
            spellCheck={false}
          />
        </label>
        {load.status === "ready" && (
          <p className="masthead__count" aria-live="polite">
            {formatCount(load.items.length)} {load.items.length === 1 ? "article" : "articles"}
            {q && <> matching “{q}”</>}
          </p>
        )}
      </header>

      <main className="index" aria-busy={load.status === "loading"}>
        {load.status === "loading" && <p className="state">Opening the library…</p>}
        {load.status === "error" && (
          <p className="state state--error" role="alert">
            {load.message}
          </p>
        )}
        {load.status === "ready" && load.items.length === 0 && (
          <p className="state">Nothing matches “{q}”. Try a broader word.</p>
        )}
        {load.status === "ready" && load.items.length > 0 && (
          <ol className="index__list">
            {load.items.map((item, i) => (
              <li key={item.id} className="entry" style={{ ["--i" as string]: Math.min(i, 12) }}>
                <a
                  className="entry__link"
                  href={`/read/${item.id}`}
                  onClick={(e) => {
                    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
                    e.preventDefault();
                    navigate(`/read/${item.id}`);
                    window.scrollTo(0, 0);
                  }}
                >
                  <span className="entry__num" aria-hidden="true">
                    {String(i + 1).padStart(3, "0")}
                  </span>
                  <span className="entry__title">{item.title}</span>
                  <span className="entry__meta">
                    <SourceBadge site={item.site} />
                    <span>
                      {formatCount(item.word_count)} words · {readingMinutes(item.word_count)} min
                    </span>
                  </span>
                </a>
              </li>
            ))}
          </ol>
        )}
      </main>
    </div>
  );
}
