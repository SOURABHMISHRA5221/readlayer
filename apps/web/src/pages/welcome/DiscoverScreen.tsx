import { useEffect, useState, type RefObject } from "react";

import { domainLabel } from "../../lib/format";
import { onboardingApi, type DiscoverItem } from "../../lib/onboardingApi";
import type { Domain } from "../../lib/profileApi";
import { readback, READBACK_AFTER } from "../../lib/readback";
import { MargoSays } from "./parts";
import { QuickCheck } from "./QuickCheck";

export const POLL_MS = 2500;
export const MAX_POLLS = 10;
const MAX_TOPICS = 6;
const MAX_CONCEPTS = 2;

interface Props {
  heading: RefObject<HTMLHeadingElement | null>;
  topics: Domain[];
  concepts: string[];
  frame: string | null;
  onEdit: () => void;
  onFinish: () => void;
  /** Decision 68 K4: the Quick check below the cards (not on a Redo: onboarding stays done). */
  quickCheck?: boolean;
}

/** The reader's answers on this screen; the server's copy seeds it, local taps win. */
interface Answers {
  picks: Record<string, boolean>; // item id → liked
}

export function DiscoverScreen({ heading, topics, concepts, frame, onEdit, onFinish, quickCheck = true }: Props) {
  const [items, setItems] = useState<DiscoverItem[] | null>(null);
  const [pending, setPending] = useState(true);
  const [answers, setAnswers] = useState<Answers>({ picks: {} });
  const [error, setError] = useState<string | null>(null);
  const [finishing, setFinishing] = useState(false);

  useEffect(() => {
    const ctrl = new AbortController();
    let polls = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const ask = async () => {
      try {
        const r = await onboardingApi.discover(topics.slice(0, MAX_TOPICS), concepts.slice(0, MAX_CONCEPTS), ctrl.signal);
        setItems(r.items);
        setAnswers((cur) => seeded(cur, r.items));
        polls += 1;
        const again = r.pending && polls < MAX_POLLS;
        setPending(again);
        if (again) timer = setTimeout(() => void ask(), POLL_MS);
      } catch {
        if (ctrl.signal.aborted) return;
        setPending(false);
        setItems((cur) => cur ?? []);
        setError("We couldn't load results. You can start anyway.");
      }
    };
    void ask();
    return () => {
      ctrl.abort();
      clearTimeout(timer);
    };
  }, [topics, concepts]);

  const pick = (item: DiscoverItem, liked: boolean) =>
    save(
      () => setAnswers((cur) => ({ ...cur, picks: { ...cur.picks, [item.id]: liked } })),
      () => onboardingApi.pick(item.id, liked),
    );
  const save = (apply: () => void, call: () => Promise<unknown>) => {
    apply();
    setError(null);
    call().catch(() => setError("That answer didn't save. Try once more."));
  };
  const finish = async () => {
    setFinishing(true);
    try {
      await onboardingApi.finish();
      onFinish();
    } catch {
      setError("That didn't save. Try again.");
      setFinishing(false);
    }
  };

  const count = Object.keys(answers.picks).length;
  const loading = items === null || (pending && items.length === 0);
  const line = count >= READBACK_AFTER && items ? readback(readbackInput(items, answers, frame)) : null;

  return (
    <section className="welcome__panel welcome__panel--wide" aria-labelledby="welcome-title" aria-busy={loading}>
      <MargoSays mood={loading ? "think" : line ? "happy" : "idle"}>
        {loading
          ? "Looking around the web for you…"
          : line ?? `Tell me what you'd open. ${READBACK_AFTER - Math.min(count, READBACK_AFTER)} more answers and I'll sum you up.`}
      </MargoSays>
      <h1 id="welcome-title" className="welcome__title" ref={heading} tabIndex={-1}>
        Here's what's out there for you
      </h1>
      {line && (
        <p className="welcome__lede">
          Not quite right?{" "}
          <button type="button" className="btn btn--link" onClick={onEdit}>
            Edit your picks
          </button>
        </p>
      )}
      <div className="welcome__body">
        {loading ? (
          <ul className="discover discover--loading" aria-hidden="true">
            {Array.from({ length: 6 }, (_, i) => (
              <li key={i} className="discover-card discover-card--ghost" />
            ))}
          </ul>
        ) : items.length === 0 ? (
          <p className="welcome__lede">Nothing new turned up just now. Your feed will fill in as you consume content.</p>
        ) : (
          <ul className="discover">
            {items.map((item) => (
              <li key={item.id}>
                <Card item={item} answers={answers} onPick={pick} />
              </li>
            ))}
          </ul>
        )}
        {quickCheck && <QuickCheck />}
      </div>
      {error && (
        <p className="welcome__error" role="alert">
          {error}
        </p>
      )}
      <div className="welcome__actions">
        {!line && (
          <button type="button" className="btn" onClick={onEdit}>
            Back
          </button>
        )}
        <button type="button" className="btn btn--primary" disabled={finishing} onClick={() => void finish()}>
          Start exploring
        </button>
      </div>
    </section>
  );
}

function seeded(cur: Answers, items: DiscoverItem[]): Answers {
  const picks = { ...cur.picks };
  for (const i of items) {
    if (i.liked !== null && !(i.id in picks)) picks[i.id] = i.liked;
  }
  return { picks };
}

export function readbackInput(items: DiscoverItem[], answers: Answers, frame: string | null) {
  const label = (i: DiscoverItem) => domainLabel(i.topic) ?? i.topic_label;
  return {
    liked: items.filter((i) => answers.picks[i.id] === true).map(label),
    skipped: items.filter((i) => answers.picks[i.id] === false).map(label),
    frame,
  };
}

interface CardProps {
  item: DiscoverItem;
  answers: Answers;
  onPick: (item: DiscoverItem, liked: boolean) => void;
}

/** Decision 68 F4: what each card is, at a glance ("Watch · 6 min"). */
const FORMAT_VERB: Record<DiscoverItem["format"], string> = { article: "Read", video: "Watch", podcast: "Listen" };
const LIKE_LABEL: Record<DiscoverItem["format"], string> = {
  article: "I'd read this",
  video: "I'd watch this",
  podcast: "I'd listen to this",
};

export function formatWord(item: Pick<DiscoverItem, "format" | "duration_or_read_time">): string {
  const s = item.duration_or_read_time;
  return s ? `${FORMAT_VERB[item.format]} · ${Math.max(1, Math.round(s / 60))} min` : FORMAT_VERB[item.format];
}

/** Answered buttons stay focusable (aria-disabled, not disabled): a keyboard reader keeps
 * their place in the list instead of being thrown back to the top of the page. */
function Card({ item, answers, onPick }: CardProps) {
  const liked = answers.picks[item.id];
  const href = item.kind === "library" && item.content_id ? `/read/${item.content_id}` : item.url;
  return (
    <article className="discover-card" data-picked={liked === undefined ? undefined : liked ? "yes" : "no"}>
      <p className="discover-card__meta">
        <span className="discover-card__topic">{item.topic_label}</span> · {item.source}
        {` · ${formatWord(item)}`}
      </p>
      <h2 className="discover-card__title">
        <a href={href} target="_blank" rel="noopener noreferrer">
          {item.title}
        </a>
      </h2>
      {item.snippet && <p className="discover-card__snippet">{item.snippet}</p>}
      <div className="discover-card__answers" role="group" aria-label={`Would you ${FORMAT_VERB[item.format].toLowerCase()} “${item.title}”?`}>
        <button type="button" className="answer" aria-pressed={liked === true} aria-disabled={liked !== undefined} onClick={() => liked === undefined && onPick(item, true)}>
          {LIKE_LABEL[item.format]}
        </button>
        <button type="button" className="answer" aria-pressed={liked === false} aria-disabled={liked !== undefined} onClick={() => liked === undefined && onPick(item, false)}>
          Not for me
        </button>
      </div>
    </article>
  );
}
