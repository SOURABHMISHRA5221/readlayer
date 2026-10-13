/**
 * The media reader (media plan §G, R10, R11): the reader's lazy chunk for a recording. Two
 * pieces share it. `MediaReader` is the sticky player and owns all behaviour: seeking from the
 * time buttons, marking the spoken paragraph, Follow. `TranscriptBody` is the article body for a
 * transcript, rendered once; the annotator owns the DOM inside it, so the player reaches the
 * paragraphs and buttons through the article element rather than through React state.
 */
import { HOST_UI, UI_ATTR } from "@readlayer/annotator";
import { memo, useCallback, useEffect, useRef, useState, type RefObject } from "react";

import { api, ApiError, type ContentDetail, type MediaInfo } from "../../lib/api";
import {
  clock,
  currentTimeOf,
  embedUrl,
  LISTENING,
  paragraphAt,
  PLAY,
  seekTo,
  shouldFollow,
  thumbnailUrl,
  YOUTUBE_ORIGIN,
} from "../../lib/media";
import { External, PlayIcon } from "../Icons";
import { PreparingNotice, StopNotice } from "./Notices";
import "./media.css";

const NOW_ATTR = "data-rl-now";
const SEEK_ATTR = "data-rl-seek";
// The player answers "listening" once its API is up; until then, ask again (a few times).
const LISTEN_EVERY_MS = 1000;
const LISTEN_TRIES = 10;
const SCROLL_KEYS = new Set(["ArrowUp", "ArrowDown", "PageUp", "PageDown", "Home", "End", " "]);
const TRANSCRIBE_WINDOW_MS = 300_000;
const TRANSCRIBE_RETRY_MS = 5000;
const TRANSCRIBE_FAILED = "Gloss couldn't transcribe this. Open the original instead.";
const TRANSCRIBE_OFFLINE = "Couldn't reach Gloss. Check your connection and try again.";

// `retry` offers "Try again": a timeout, a busy service, the budget, or offline.
type Transcription =
  | { status: "idle" }
  | { status: "running"; since: number }
  | { status: "failed"; message: string; retry: boolean };

type Paragraphs = ContentDetail["paragraphs"];

interface MediaReaderProps {
  contentId: string;
  media: MediaInfo;
  title: string;
  url: string;
  paragraphs: Paragraphs;
  /** The transcript's <article> (the annotator's root): time buttons and paragraphs live there. */
  article: RefObject<HTMLElement | null>;
  /** No transcript yet: call POST .../transcribe; the player works meanwhile. */
  transcribing: boolean;
  /** The transcript is in: the reloaded content (status "analysing"). */
  onTranscribed: (content: ContentDetail) => void;
}

export default function MediaReader(props: MediaReaderProps) {
  const transcription = useTranscription(props.contentId, props.transcribing, props.onTranscribed);
  return (
    <>
      {props.media.kind === "video" && props.media.video_id && <VideoPlayer {...props} videoId={props.media.video_id} />}
      {transcription.state.status === "running" && (
        <PreparingNotice since={transcription.state.since} text="Gloss is listening to this. About a minute." />
      )}
      {transcription.state.status === "failed" && (
        <StopNotice message={transcription.state.message} url={props.url} onRetry={transcription.state.retry ? transcription.retry : undefined} />
      )}
    </>
  );
}

/**
 * The transcript, asked for until it's done: 202 (someone else is on it) waits 5 s and asks
 * again; a timeout is retried once automatically (R4.2), then the reader may try again.
 */
function useTranscription(id: string, active: boolean, onDone: (content: ContentDetail) => void) {
  const [state, setState] = useState<Transcription>({ status: "idle" });
  const [round, setRound] = useState(0);
  const doneRef = useRef(onDone);
  doneRef.current = onDone;
  useEffect(() => {
    if (!active) return;
    const ctrl = new AbortController();
    const since = Date.now();
    setState({ status: "running", since });
    void (async () => {
      let timedOut = false;
      while (!ctrl.signal.aborted && Date.now() - since < TRANSCRIBE_WINDOW_MS) {
        try {
          if ((await api.transcribe(id, ctrl.signal)) === "done") {
            const content = await api.content(id, ctrl.signal);
            setState({ status: "idle" });
            doneRef.current(content);
            return;
          }
        } catch (e: unknown) {
          if (ctrl.signal.aborted) return;
          if (e instanceof ApiError && e.status === 504 && !timedOut) {
            timedOut = true;
            continue;
          }
          setState(transcribeFailure(e));
          return;
        }
        await new Promise((r) => setTimeout(r, TRANSCRIBE_RETRY_MS));
      }
      if (!ctrl.signal.aborted) setState({ status: "failed", message: TRANSCRIBE_FAILED, retry: true });
    })();
    return () => ctrl.abort();
  }, [id, active, round]);
  const retry = useCallback(() => setRound((n) => n + 1), []);
  return { state, retry };
}

function transcribeFailure(e: unknown): Transcription {
  if (!(e instanceof ApiError) || e.kind === "offline") return { status: "failed", message: TRANSCRIBE_OFFLINE, retry: true };
  // A timeout after the automatic retry, a busy service or the budget: worth another go later.
  const retry = e.status === 504 || e.status === 503 || e.status === 429;
  return { status: "failed", message: e.detail ?? TRANSCRIBE_FAILED, retry };
}

function VideoPlayer({ title, url, paragraphs, article, videoId }: MediaReaderProps & { videoId: string }) {
  const [start, setStart] = useState<number | null>(null); // null: the facade, no iframe yet
  const [follow, setFollow] = useState(true);
  const frame = useRef<HTMLIFrameElement>(null);
  const bar = useRef<HTMLDivElement>(null);
  const heard = useRef(false);
  const manualAt = useRef(0);
  const followRef = useRef(follow);
  followRef.current = follow;
  const startsRef = useRef<number[]>([]);
  startsRef.current = paragraphs.map((p) => p.start_s ?? 0);
  const nowRef = useRef(-1);

  const mark = useCallback(
    (t: number) => {
      const i = paragraphAt(startsRef.current, t);
      if (i === nowRef.current) return;
      nowRef.current = i;
      const root = article.current;
      if (!root) return;
      root.querySelectorAll(`[${NOW_ATTR}]`).forEach((el) => el.removeAttribute(NOW_ATTR));
      const el = i >= 0 ? root.querySelectorAll<HTMLElement>("[data-rl-paragraph]")[i] : undefined;
      if (!el) return;
      el.setAttribute(NOW_ATTR, "");
      if (shouldFollow(followRef.current, manualAt.current, Date.now())) keepInView(el, bar.current);
    },
    [article],
  );

  const seek = useCallback(
    (s: number) => {
      mark(s);
      const win = frame.current?.contentWindow;
      if (!win) {
        setStart(s); // first play: the iframe loads at this time and starts playing
        return;
      }
      win.postMessage(seekTo(s), YOUTUBE_ORIGIN);
      win.postMessage(PLAY, YOUTUBE_ORIGIN);
    },
    [mark],
  );

  // Time buttons, by delegation: they are rendered inside the annotator's root.
  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      const target = e.target instanceof Element ? e.target.closest<HTMLElement>(`[${SEEK_ATTR}]`) : null;
      if (!target || !article.current?.contains(target)) return;
      const s = Number(target.getAttribute(SEEK_ATTR));
      if (Number.isFinite(s)) seek(s);
    };
    document.addEventListener("click", onClick);
    return () => document.removeEventListener("click", onClick);
  }, [article, seek]);

  // The player's time, from our own iframe only.
  useEffect(() => {
    const onMessage = (e: MessageEvent) => {
      const t = currentTimeOf(e, frame.current?.contentWindow ?? null);
      if (t === null) return;
      heard.current = true;
      mark(t);
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [mark]);

  // A wheel, touch or scroll key means the reader is looking elsewhere: Follow waits 5 s.
  useEffect(() => {
    const manual = () => {
      manualAt.current = Date.now();
    };
    const onKey = (e: KeyboardEvent) => {
      if (SCROLL_KEYS.has(e.key) && !(e.target instanceof HTMLButtonElement && e.key === " ")) manual();
    };
    window.addEventListener("wheel", manual, { passive: true });
    window.addEventListener("touchmove", manual, { passive: true });
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("wheel", manual);
      window.removeEventListener("touchmove", manual);
      window.removeEventListener("keydown", onKey);
    };
  }, []);

  const onFrameLoad = () => {
    heard.current = false;
    let tries = 0;
    const ask = () => {
      const win = frame.current?.contentWindow;
      if (!win || heard.current || tries++ >= LISTEN_TRIES) return;
      win.postMessage(LISTENING, YOUTUBE_ORIGIN);
      setTimeout(ask, LISTEN_EVERY_MS);
    };
    ask();
  };

  return (
    <div className="mplayer" ref={bar}>
      <div className="mplayer__screen">
        {start === null ? (
          <button type="button" className="mplayer__facade" onClick={() => setStart(0)} aria-label={`Play video: ${title}`}>
            <img src={thumbnailUrl(videoId)} alt="" referrerPolicy="no-referrer" width={480} height={360} decoding="async" />
            <span className="mplayer__play" aria-hidden="true">
              <PlayIcon size={28} />
            </span>
          </button>
        ) : (
          <iframe
            ref={frame}
            src={embedUrl(videoId, window.location.origin, start)}
            title={`Video: ${title}`}
            allow="autoplay; encrypted-media; picture-in-picture; fullscreen"
            referrerPolicy="strict-origin"
            allowFullScreen
            onLoad={onFrameLoad}
          />
        )}
      </div>
      <div className="mplayer__bar">
        <button type="button" className="filter mplayer__follow" aria-pressed={follow} onClick={() => setFollow((f) => !f)}>
          Follow along
        </button>
        <a className="mplayer__original" href={url} target="_blank" rel="noopener noreferrer">
          Open on YouTube <External size={13} />
          <span className="visually-hidden"> (opens in a new tab)</span>
        </a>
      </div>
    </div>
  );
}

/** Scrolls the spoken paragraph into view below the sticky player, only when it's out of view. */
function keepInView(el: HTMLElement, player: HTMLElement | null): void {
  const view = el.ownerDocument.defaultView;
  if (!view) return;
  const top = player ? player.getBoundingClientRect().bottom : 0;
  const box = el.getBoundingClientRect();
  if (box.top >= top && box.top < view.innerHeight * 0.75) return;
  const reduce = view.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
  view.scrollTo({ top: view.scrollY + box.top - top - 24, behavior: reduce ? "auto" : "smooth" });
}

interface TranscriptBodyProps {
  paragraphs: Paragraphs;
  ref: React.Ref<HTMLElement>;
  /** Called once mounted: the annotator may attach to the article now. */
  onMount: () => void;
}

/** Re-renders only when the transcript arrives (paragraphs change); the annotator mounts after. */
export const TranscriptBody = memo(function TranscriptBody({ paragraphs, ref, onMount }: TranscriptBodyProps) {
  useEffect(onMount, [onMount]);
  return (
    <article className="prose prose--transcript" ref={ref}>
      {paragraphs.map((p) => (
        <p key={p.id} data-rl-paragraph={p.id}>
          {p.start_s != null && (
            <button
              type="button"
              className="tstamp tnum"
              {...{ [UI_ATTR]: HOST_UI, [SEEK_ATTR]: p.start_s }}
              aria-label={`Play from ${clock(p.start_s)}`}
            >
              {clock(p.start_s)}
            </button>
          )}
          {p.text}
        </p>
      ))}
    </article>
  );
});
