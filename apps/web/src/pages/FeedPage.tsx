import { useEffect, useState } from "react";

import { AccountMenu } from "../components/AccountMenu";
import { LibraryTabs } from "../components/LibraryTabs";
import { PersonaPicker } from "../components/PersonaPicker";
import { ERROR_COPY, StateView } from "../components/StateView";
import { ThemeToggle } from "../components/ThemeToggle";
import { sendRecEvent } from "../components/UpNext";
import { Wordmark } from "../components/Wordmark";
import { api, ApiError, errorKind, type ApiErrorKind } from "../lib/api";
import { useIsDemo } from "../lib/auth";
import { feedApi, type FeedItem, type FeedResponse } from "../lib/feedApi";
import { pendingNote, reaskDelay, snapshotNote, visibleItems } from "../lib/feedView";
import { formatDate } from "../lib/format";
import { DEFAULT_PERSONA, personaParam, readerPersona, type PersonaKey } from "../lib/personas";
import { navigate, withParams } from "../lib/router";
import "../styles/feed.css";


type Load = { status: "loading" } | { status: "ready"; feed: FeedResponse } | { status: "error"; kind: ApiErrorKind };

function length(item: FeedItem): string {
  const s = item.duration_or_read_time;
  if (item.format === "article") return s ? `${Math.max(1, Math.round(s / 60))} min read` : "Article";
  if (!s) return item.format === "video" ? "Video" : "Podcast episode";
  return `${Math.round(s / 60)} min ${item.format === "video" ? "video" : "episode"}`;
}

/** For you (M7.5): picks per interest topic. Demo personas see a snapshot prepared in advance. */
export default function FeedPage({ url }: { url: URL }) {
  const persona = readerPersona(url, useIsDemo());
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    document.title = "For you · ReadLayer";
  }, []);

  useEffect(() => {
    const ctrl = new AbortController();
    feedApi
      .feed(persona, ctrl.signal)
      .then((feed) => setLoad({ status: "ready", feed }))
      .catch((e) => !ctrl.signal.aborted && setLoad({ status: "error", kind: errorKind(e) }));
    return () => ctrl.abort();
  }, [persona, attempt]);

  // Searches still running: ask again a few times (they finish on the server meanwhile).
  const pending = load.status === "ready" && load.feed.pending;
  useEffect(() => {
    const delay = reaskDelay(pending, attempt);
    if (delay === null) return;
    const t = setTimeout(() => setAttempt((a) => a + 1), delay);
    return () => clearTimeout(t);
  }, [pending, attempt]);

  const setPersona = (k: PersonaKey) =>
    navigate(withParams(url, { persona: k === DEFAULT_PERSONA ? null : k }), { replace: true });

  return (
    <>
      <header className="masthead masthead--slim">
        <div className="masthead__bar">
          <Wordmark size="lg" />
          <div className="masthead__tools">
            {persona && <PersonaPicker value={persona} onChange={setPersona} />}
            <ThemeToggle />
            <AccountMenu />
          </div>
        </div>
        <LibraryTabs current="feed" persona={persona} />
      </header>
      <main className="feed" id="feed" tabIndex={-1}>
        <h1 className="feed__title">For you</h1>
        {load.status === "loading" && <p className="feed__note" role="status">Finding picks for you…</p>}
        {load.status === "error" && (
          <StateView
            title={ERROR_COPY[load.kind].title}
            role="alert"
            actions={
              <button className="btn btn--primary" type="button" onClick={() => setAttempt((a) => a + 1)}>
                Try again
              </button>
            }
          >
            <p>{ERROR_COPY[load.kind].body}</p>
          </StateView>
        )}
        {load.status === "ready" && <FeedBody feed={load.feed} persona={persona} attempt={attempt} />}
      </main>
    </>
  );
}

function FeedBody({ feed, persona, attempt }: { feed: FeedResponse; persona: PersonaKey | null; attempt: number }) {
  const [dismissed, setDismissed] = useState<ReadonlySet<string>>(new Set());
  const [announce, setAnnounce] = useState("");
  const shown = visibleItems(feed.items, dismissed);
  const note = snapshotNote(feed, (iso) => formatDate(iso) ?? iso);
  const waiting = pendingNote(feed.pending, attempt);

  const dismiss = (item: FeedItem) => {
    sendRecEvent(persona, "rec_dismissed", item.id);
    setDismissed((d) => new Set([...d, item.id]));
    setAnnounce(`Removed “${item.title}”. You won't see it again.`);
  };

  return (
    <>
      {note && <p className="feed__note">{note}</p>}
      {waiting && <p className="feed__note" role="status">{waiting}</p>}
      <p className="visually-hidden" aria-live="polite">{announce}</p>
      {!shown.length && !feed.pending && (
        <p className="feed__note">
          {feed.snapshot ? "This demo feed isn't ready yet. Sign in with Google for a live feed." : "Fresh picks arrive tomorrow."}
        </p>
      )}
      {feed.topics.map((topic) => {
        const items = shown.filter((i) => i.topic === topic);
        if (!items.length) return null;
        return (
          <section key={topic} className="feed__topic" aria-labelledby={`t-${topic}`}>
            <h2 id={`t-${topic}`} className="feed__topic-title">{items[0]?.topic_label ?? topic}</h2>
            <ul className="feed__list">
              {items.map((item) => (
                <li key={item.id}>
                  <FeedCard item={item} persona={persona} onDismiss={dismiss} />
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </>
  );
}

type FeedCardProps = { item: FeedItem; persona: PersonaKey | null; onDismiss: (item: FeedItem) => void };

function FeedCard({ item, persona, onDismiss }: FeedCardProps) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => sendRecEvent(persona, "rec_shown", item.id), [persona, item.id]);

  const openHere = async () => {
    sendRecEvent(persona, "rec_clicked", item.id);
    setBusy(true);
    try {
      const { content_id } = await api.openWeb(item.url);
      navigate(withParams(new URL(`/read/${content_id}`, window.location.origin), { persona: personaParam(persona) }));
      window.scrollTo(0, 0);
    } catch (e) {
      setBusy(false);
      setError(e instanceof ApiError && e.detail ? e.detail : "That page couldn't be opened here. Try the original.");
    }
  };

  return (
    <article className="fcard" data-format={item.format} aria-labelledby={`f-${item.id}`}>
      <div className="fcard__body">
        <p className="fcard__meta">
          {item.source} · {length(item)}
        </p>
        <h3 id={`f-${item.id}`} className="fcard__title">{item.title}</h3>
        {item.snippet && <p className="fcard__snippet">{item.snippet}</p>}
        <p className="fcard__why">{item.why}</p>
        <div className="fcard__actions">
          {item.format === "article" && (
            <button className="btn" type="button" onClick={openHere} disabled={busy}>
              {busy ? "Opening…" : "Read here"}
            </button>
          )}
          <a className="btn btn--quiet" href={item.url} target="_blank" rel="noopener noreferrer"
            onClick={() => sendRecEvent(persona, "rec_clicked", item.id)}>
            {item.format === "video" ? "Watch" : item.format === "podcast" ? "Listen" : "Open original"}
            <span className="visually-hidden"> (opens in a new tab)</span>
          </a>
          <button className="btn btn--quiet" type="button" onClick={() => onDismiss(item)}
            aria-label={`Not interested: ${item.title}`}>
            Not interested
          </button>
        </div>
        {error && <p className="fcard__error" role="alert">{error}</p>}
      </div>
      {item.thumbnail && (
        <img className="fcard__thumb" src={item.thumbnail} alt="" loading="lazy" referrerPolicy="no-referrer"
          onError={(e) => { e.currentTarget.hidden = true; }} />
      )}
    </article>
  );
}
