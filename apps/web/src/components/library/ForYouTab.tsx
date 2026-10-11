import { useEffect, useState } from "react";

import { api, ApiError, errorKind, type ApiErrorKind } from "../../lib/api";
import { feedApi, type FeedItem, type FeedResponse } from "../../lib/feedApi";
import { FEED_STALE } from "../../lib/feedStale";
import { pendingNote, reaskDelay, snapshotNote, visibleItems, wantsCountry } from "../../lib/feedView";
import { formatDate } from "../../lib/format";
import { personaParam, type PersonaKey } from "../../lib/personas";
import { navigate, withParams } from "../../lib/router";
import { ERROR_COPY, StateView } from "../StateView";
import { sendRecEvent } from "../UpNext";
import { Row } from "./Row";

type Load = { status: "loading" } | { status: "ready"; feed: FeedResponse } | { status: "error"; kind: ApiErrorKind };

const VERB = { article: "read", video: "watch", podcast: "listen" } as const;

function time(item: FeedItem): string {
  const s = item.duration_or_read_time;
  if (!s) return item.format === "article" ? "Article" : item.format === "video" ? "Video" : "Podcast";
  return `${Math.max(1, Math.round(s / 60))} min ${VERB[item.format]}`;
}

/** For you (M7.5 feed) as rows: lazy chunk of the library page (Design pass C5). */
export default function ForYouTab({ persona }: { persona: PersonaKey | null }) {
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [round, setRound] = useState(0); // bumped by Refresh and by preference changes
  const [refreshing, setRefreshing] = useState(false);
  const [dismissed, setDismissed] = useState<ReadonlySet<string>>(new Set());
  const [opening, setOpening] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [announce, setAnnounce] = useState("");

  useEffect(() => {
    const ctrl = new AbortController();
    feedApi
      .feed(persona, ctrl.signal)
      .then((feed) => setLoad({ status: "ready", feed }))
      .catch((e) => !ctrl.signal.aborted && setLoad({ status: "error", kind: errorKind(e) }))
      .finally(() => !ctrl.signal.aborted && setRefreshing(false));
    return () => ctrl.abort();
  }, [persona, attempt, round]);

  // A refresh keeps the current picks on screen until the new ones arrive (decision 50 §F).
  const refresh = () => {
    setRefreshing(true);
    setAttempt(0);
    setRound((r) => r + 1);
  };
  useEffect(() => {
    const onStale = () => refresh();
    window.addEventListener(FEED_STALE, onStale);
    return () => window.removeEventListener(FEED_STALE, onStale);
  }, []);

  const pending = load.status === "ready" && load.feed.pending;
  useEffect(() => {
    const delay = reaskDelay(pending, attempt);
    if (delay === null) return;
    const t = setTimeout(() => setAttempt((a) => a + 1), delay);
    return () => clearTimeout(t);
  }, [pending, attempt]);

  if (load.status === "loading") return <p className="feedtab__note" role="status">Finding picks for you…</p>;
  if (load.status === "error")
    return (
      <StateView
        title={ERROR_COPY[load.kind].title}
        role="alert"
        margo="oops"
        actions={
          <button className="btn btn--primary" type="button" onClick={() => setAttempt((a) => a + 1)}>
            Try again
          </button>
        }
      >
        {ERROR_COPY[load.kind].body}
      </StateView>
    );

  const feed = load.feed;
  const shown = visibleItems(feed.items, dismissed);
  const note = snapshotNote(feed, (iso) => formatDate(iso) ?? iso);
  const waiting = pendingNote(feed.pending, attempt);

  const openHere = async (item: FeedItem) => {
    sendRecEvent(persona, "rec_clicked", item.id);
    setOpening(item.id);
    try {
      const { content_id } = await api.openWeb(item.url);
      navigate(withParams(new URL(`/read/${content_id}`, window.location.origin), { persona: personaParam(persona) }));
      window.scrollTo(0, 0);
    } catch (e) {
      setOpening(null);
      setErrors((x) => ({ ...x, [item.id]: e instanceof ApiError && e.detail ? e.detail : "That page couldn't be opened here. Try the original." }));
    }
  };
  const less = (item: FeedItem) => {
    sendRecEvent(persona, "rec_dismissed", item.id);
    setDismissed((d) => new Set([...d, item.id]));
    setAnnounce(`Removed “${item.title}”. You'll see less like it.`);
  };

  return (
    <div className="feedtab" aria-busy={refreshing}>
      {!feed.snapshot && (
        <div className="feedtab__bar">
          <p className="feedtab__note" role="status">
            {refreshing ? "Refreshing your picks…" : wantsCountry(feed) ? (
              <>
                Add your country for news from where you live. <a
                  href="/profile#prefs-title"
                  onClick={(e) => {
                    e.preventDefault();
                    navigate("/profile#prefs-title");
                  }}
                >
                  Preferences
                </a>
              </>
            ) : null}
          </p>
          <button className="btn btn--sm feedtab__refresh" type="button" onClick={refresh} disabled={refreshing}>
            Refresh
          </button>
        </div>
      )}
      {note && <p className="feedtab__note">{note}</p>}
      {waiting && (
        <p className="feedtab__note" role="status">
          {waiting}
        </p>
      )}
      <p className="visually-hidden" aria-live="polite">
        {announce}
      </p>
      {!shown.length && !feed.pending && (
        <StateView title={feed.snapshot ? "This demo feed isn't ready yet" : "Fresh picks arrive tomorrow"} margo="oops">
          {feed.snapshot ? "Sign in with Google for a live feed." : "Meanwhile, the Topics tab has the whole library."}
        </StateView>
      )}
      <ul className="rows">
        {shown.map((item) => (
          <li key={item.id}>
            <ShownOnce persona={persona} id={item.id} />
            <Row
              source={item.source}
              context={`in ${item.topic_label}${item.format === "article" ? "" : ` · ${item.format}`}`}
              title={item.title}
              href={item.url}
              external={item.format !== "article"}
              onOpen={item.format === "article" ? () => openHere(item) : undefined}
              subtitle={item.snippet}
              why={item.goal ? <>Picked for your goal <b>{item.goal}</b></> : null}
              time={time(item)}
              newCount={item.new_concepts.length}
              goal={null}
              saved={null}
              onLess={() => less(item)}
              busy={opening === item.id}
              error={errors[item.id]}
              thumbnail={
                item.thumbnail ? (
                  <img src={item.thumbnail} alt="" loading="lazy" referrerPolicy="no-referrer" width={120} height={120}
                    onError={(e) => { const box = e.currentTarget.parentElement; if (box) box.hidden = true; }} />
                ) : null
              }
            />
          </li>
        ))}
      </ul>
    </div>
  );
}

/** One rec_shown per card per mount (the server records impressions only after consent). */
function ShownOnce({ persona, id }: { persona: PersonaKey | null; id: string }) {
  useEffect(() => sendRecEvent(persona, "rec_shown", id), [persona, id]);
  return null;
}
