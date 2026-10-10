import { useCallback, useEffect, useRef, useState } from "react";

import { api, errorKind, ApiError, type RecEventType, type RecFormat, type RecItem } from "../lib/api";
import { queueRecEvent } from "../lib/recEvents";
import { sourceMonogram, sourceName } from "../lib/format";
import { personaParam, type PersonaKey } from "../lib/personas";
import { navigate, withParams } from "../lib/router";
import { ArticleIcon, Close, External, HeadphonesIcon, PlayIcon } from "./Icons";

const POLL_MS = 1500;
const MAX_POLLS = 8;
const PREF_KEY = "readlayer:format-pref:";

const FORMAT_CHOICES: { key: RecFormat; label: string }[] = [
  { key: "article", label: "Read" },
  { key: "video", label: "Watch" },
  { key: "podcast", label: "Listen" },
];

type Load =
  | { status: "loading" }
  | { status: "ready"; items: RecItem[]; pending: boolean }
  | { status: "error" };

function readPref(persona: PersonaKey | null): RecFormat | null {
  try {
    const v = window.localStorage.getItem(PREF_KEY + (persona ?? "me"));
    return v === "article" || v === "video" || v === "podcast" ? v : null;
  } catch {
    return null;
  }
}

function writePref(persona: PersonaKey | null, pref: RecFormat | null): void {
  try {
    if (pref) window.localStorage.setItem(PREF_KEY + (persona ?? "me"), pref);
    else window.localStorage.removeItem(PREF_KEY + (persona ?? "me"));
  } catch {
    // Storage blocked: the preference lasts for this page only.
  }
}

export function sendRecEvent(persona: PersonaKey | null, type: RecEventType, itemId: string): void {
  queueRecEvent(persona, type, itemId);
}

export function formatLength(item: Pick<RecItem, "format" | "duration_or_read_time">): string {
  const s = item.duration_or_read_time;
  if (item.format === "article") return s ? `${Math.max(1, Math.round(s / 60))} min read` : "Article";
  if (!s) return item.format === "video" ? "Video" : "Podcast episode";
  const m = Math.floor(s / 60);
  if (m >= 60) return `${Math.floor(m / 60)} h ${m % 60} min`;
  return item.format === "video" ? `${m}:${String(s % 60).padStart(2, "0")}` : `${m} min`;
}

/** End-of-article recommendations for this reader, mixing our library with the web. */
export function UpNext({ contentId, persona }: { contentId: string; persona: PersonaKey | null }) {
  const [pref, setPref] = useState<RecFormat | null>(() => readPref(persona));
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());

  useEffect(() => setPref(readPref(persona)), [persona]);

  useEffect(() => {
    const ctrl = new AbortController();
    let polls = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const fetchOnce = () => {
      api
        .recommendations(contentId, persona, pref, ctrl.signal)
        .then((data) => {
          setLoad({ status: "ready", items: data.items, pending: data.pending });
          if (data.pending && polls++ < MAX_POLLS) timer = setTimeout(fetchOnce, POLL_MS);
        })
        .catch(() => {
          if (!ctrl.signal.aborted) setLoad({ status: "error" });
        });
    };
    fetchOnce();
    return () => {
      ctrl.abort();
      clearTimeout(timer);
    };
  }, [contentId, persona, pref]);

  const choosePref = (key: RecFormat) => {
    const next = pref === key ? null : key;
    setPref(next);
    writePref(persona, next);
  };

  const dismiss = useCallback(
    (item: RecItem) => {
      sendRecEvent(persona, "rec_dismissed", item.id);
      setDismissed((prev) => new Set(prev).add(item.id));
    },
    [persona],
  );

  const items = load.status === "ready" ? load.items.filter((i) => !dismissed.has(i.id)) : [];

  return (
    <section className="upnext" aria-labelledby="upnext-title">
      <div className="upnext__head">
        <div>
          <p className="eyebrow">Up next</p>
          <h2 id="upnext-title" className="upnext__title">
            Keep going, your way
          </h2>
        </div>
        <div className="upnext__pref" role="group" aria-label="Show me more to">
          {FORMAT_CHOICES.map((f) => (
            <button
              key={f.key}
              type="button"
              className="filter"
              aria-pressed={pref === f.key}
              onClick={() => choosePref(f.key)}
            >
              <FormatIcon format={f.key} size={15} />
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {load.status === "loading" && <UpNextSkeleton />}
      {load.status === "error" && (
        <p className="upnext__note" role="status">
          Suggestions aren't available right now. The library has plenty more to read.
        </p>
      )}
      {load.status === "ready" && items.length === 0 && !load.pending && (
        <p className="upnext__note" role="status">
          Nothing to suggest for this one yet.
        </p>
      )}
      {items.length > 0 && (
        <ul className="upnext__grid">
          {items.map((item) => (
            <li key={item.id}>
              <RecCard item={item} persona={persona} fromId={contentId} onDismiss={dismiss} />
            </li>
          ))}
        </ul>
      )}
      {load.status === "ready" && load.pending && (
        <p className="upnext__note upnext__note--live" aria-live="polite">
          Looking for videos, podcasts and explainers on the web…
        </p>
      )}
    </section>
  );
}

function FormatIcon({ format, size = 16 }: { format: RecFormat; size?: number }) {
  if (format === "video") return <PlayIcon size={size} />;
  if (format === "podcast") return <HeadphonesIcon size={size} />;
  return <ArticleIcon size={size} />;
}

const FORMAT_NAME: Record<RecFormat, string> = { article: "Article", video: "Video", podcast: "Podcast" };

interface RecCardProps {
  item: RecItem;
  persona: PersonaKey | null;
  fromId: string;
  onDismiss: (item: RecItem) => void;
}

function RecCard({ item, persona, fromId, onDismiss }: RecCardProps) {
  const ref = useRef<HTMLElement>(null);
  const [opening, setOpening] = useState<
    { status: "idle" } | { status: "busy"; since: number } | { status: "error"; message: string }
  >({ status: "idle" });
  const [, tick] = useState(0);

  useEffect(() => {
    if (opening.status !== "busy") return;
    const t = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, [opening.status]);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting) {
          sendRecEvent(persona, "rec_shown", item.id);
          observer.disconnect();
        }
      },
      { threshold: 0.6 },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [item.id, persona]);

  const readerHref = (id: string) =>
    withParams(new URL(`/read/${id}`, window.location.origin), {
      persona: personaParam(persona),
      rec: item.id,
      from: fromId,
    });

  const openHere = async () => {
    sendRecEvent(persona, "rec_clicked", item.id);
    setOpening({ status: "busy", since: Date.now() });
    try {
      const { content_id } = await api.openWeb(item.url);
      navigate(readerHref(content_id));
      window.scrollTo(0, 0);
    } catch (error) {
      const message =
        error instanceof ApiError && error.detail
          ? error.detail
          : errorKind(error) === "offline"
            ? "Couldn't reach ReadLayer. Try again, or open the original."
            : "That page couldn't be opened here. Try the original instead.";
      setOpening({ status: "error", message });
    }
  };

  const [thumbFailed, setThumbFailed] = useState(false);
  const isWeb = item.kind === "web";
  const source = isWeb ? item.source : sourceName(item.source);
  const titleId = `rec-${item.id.replace(/[^a-z0-9]/gi, "")}`;

  return (
    <article className="rec" ref={ref} aria-labelledby={titleId} data-format={item.format}>
      <div className="rec__media">
        {item.thumbnail && !thumbFailed ? (
          <img
            src={item.thumbnail}
            alt=""
            loading="lazy"
            decoding="async"
            referrerPolicy="no-referrer"
            width={480}
            height={270}
            onError={() => setThumbFailed(true)}
          />
        ) : item.kind === "library" ? (
          // A hotlinked image that fails (or none) becomes the same typographic tile as the library.
          <div className="media__tile" aria-hidden="true">
            <span className="media__monogram">{sourceMonogram(item.source)}</span>
          </div>
        ) : (
          <span className="rec__media-icon" aria-hidden="true">
            <FormatIcon format={item.format} size={28} />
          </span>
        )}
        {item.format !== "article" && item.duration_or_read_time ? (
          <span className="rec__duration tnum">{formatLength(item)}</span>
        ) : null}
      </div>
      <div className="rec__body">
        <div className="rec__top">
          <span className="rec__relation eyebrow">{item.relation_label}</span>
          <span className="rec__format" title={FORMAT_NAME[item.format]}>
            <FormatIcon format={item.format} size={15} />
            <span className="visually-hidden">{FORMAT_NAME[item.format]}</span>
          </span>
          {isWeb && <span className="rec__web">From the web</span>}
        </div>
        <h3 className="rec__title" id={titleId}>
          {item.kind === "library" && item.content_id ? (
            <a
              href={readerHref(item.content_id)}
              onClick={(e) => {
                sendRecEvent(persona, "rec_clicked", item.id);
                if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
                e.preventDefault();
                navigate(readerHref(item.content_id!));
                window.scrollTo(0, 0);
              }}
            >
              {item.title}
            </a>
          ) : (
            <a
              href={item.url}
              target="_blank"
              rel="noopener noreferrer"
              onClick={() => sendRecEvent(persona, "rec_clicked", item.id)}
            >
              {item.title}
              <span className="visually-hidden"> (opens in a new tab)</span>
            </a>
          )}
        </h3>
        <p className="rec__meta tnum">
          {source} · {formatLength(item)}
        </p>
        <p className="rec__why">{item.why}</p>
        {item.triggers[0] && <span className="rec__trigger">{item.triggers[0].label}</span>}

        <div className="rec__actions">
          {item.kind === "library" && item.content_id && (
            <a
              className="btn btn--sm"
              href={readerHref(item.content_id)}
              onClick={(e) => {
                sendRecEvent(persona, "rec_clicked", item.id);
                if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
                e.preventDefault();
                navigate(readerHref(item.content_id!));
                window.scrollTo(0, 0);
              }}
            >
              Read with notes
            </a>
          )}
          {isWeb && item.format === "article" && (
            <>
              <button type="button" className="btn btn--sm" onClick={openHere} disabled={opening.status === "busy"}>
                {opening.status === "busy" ? "Opening…" : "Open here"}
              </button>
              <a className="rec__original" href={item.url} target="_blank" rel="noopener noreferrer" onClick={() => sendRecEvent(persona, "rec_clicked", item.id)}>
                Open original <External size={13} />
                <span className="visually-hidden"> (opens in a new tab)</span>
              </a>
            </>
          )}
          {isWeb && item.format !== "article" && (
            <a className="btn btn--sm" href={item.url} target="_blank" rel="noopener noreferrer" onClick={() => sendRecEvent(persona, "rec_clicked", item.id)}>
              {item.format === "video" ? "Watch" : "Listen"} on {item.format === "video" ? "YouTube" : sourceLabel(item.source)} <External size={13} />
              <span className="visually-hidden"> (opens in a new tab)</span>
            </a>
          )}
          <button type="button" className="icon-btn rec__dismiss" aria-label={`Not for me: ${item.title}`} title="Not for me" onClick={() => onDismiss(item)}>
            <Close size={16} />
          </button>
        </div>
        {opening.status === "busy" && (
          <div className="rec__progress" role="status">
            <span className="rec__bar" aria-hidden="true" />
            <span>
              Fetching the page. It opens as soon as it's in; your notes follow.{" "}
              <span className="tnum" aria-hidden="true">
                {Math.round((Date.now() - opening.since) / 1000)} s
              </span>
            </span>
          </div>
        )}
        {opening.status === "error" && (
          <p className="rec__error" role="alert">
            {opening.message}
          </p>
        )}
      </div>
    </article>
  );
}

function sourceLabel(host: string): string {
  if (host.includes("spotify")) return "Spotify";
  if (host.includes("apple")) return "Apple Podcasts";
  return host;
}

function UpNextSkeleton() {
  return (
    <ul className="upnext__grid" aria-busy="true" aria-label="Loading suggestions">
      {Array.from({ length: 3 }, (_, i) => (
        <li key={i}>
          <div className="rec rec--skeleton">
            <div className="skeleton rec__media" />
            <div className="rec__body">
              <div className="skeleton" style={{ width: 120, height: 12 }} />
              <div className="skeleton" style={{ width: "90%", height: 18, marginTop: 10 }} />
              <div className="skeleton" style={{ width: "60%", height: 18, marginTop: 6 }} />
            </div>
          </div>
        </li>
      ))}
    </ul>
  );
}
