import { useEffect, useState, type RefObject } from "react";

import { domainLabel } from "../../lib/format";
import { onboardingApi, type DiscoverItem } from "../../lib/onboardingApi";
import type { Domain } from "../../lib/profileApi";
import { readback, READBACK_AFTER } from "../../lib/readback";
import { MargoSays } from "./parts";

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
}

/** The reader's answers on this screen; the server's copy seeds it, local taps win. */
interface Answers {
  picks: Record<string, boolean>; // item id → liked
  known: Record<string, boolean>; // concept id → known
}

export function DiscoverScreen({ heading, topics, concepts, frame, onEdit, onFinish }: Props) {
  const [items, setItems] = useState<DiscoverItem[] | null>(null);
  const [pending, setPending] = useState(true);
  const [answers, setAnswers] = useState<Answers>({ picks: {}, known: {} });
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
        setError("We couldn't load results. You can start reading anyway.");
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
  const know = (conceptId: string, known: boolean) =>
    save(
      () => setAnswers((cur) => ({ ...cur, known: { ...cur.known, [conceptId]: known } })),
      () => onboardingApi.know(conceptId, known),
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

  const count = Object.keys(answers.picks).length + Object.keys(answers.known).length;
  const loading = items === null || (pending && items.length === 0);
  const line = count >= READBACK_AFTER && items ? readback(readbackInput(items, answers, frame)) : null;

  return (
    <section className="welcome__panel welcome__panel--wide" aria-labelledby="welcome-title" aria-busy={loading}>
      <MargoSays mood={loading ? "think" : line ? "happy" : "idle"}>
        {loading
          ? "Looking around the web for you…"
          : line ?? `Tell me what you'd read. ${READBACK_AFTER - Math.min(count, READBACK_AFTER)} more answers and I'll sum you up.`}
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
          <p className="welcome__lede">Nothing new turned up just now. Your feed will fill in as you read.</p>
        ) : (
          <ul className="discover">
            {items.map((item) => (
              <li key={item.id}>
                <Card item={item} answers={answers} onPick={pick} onKnow={know} />
              </li>
            ))}
          </ul>
        )}
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
          Start reading
        </button>
      </div>
    </section>
  );
}

function seeded(cur: Answers, items: DiscoverItem[]): Answers {
  const picks = { ...cur.picks };
  const known = { ...cur.known };
  for (const i of items) {
    if (i.liked !== null && !(i.id in picks)) picks[i.id] = i.liked;
    if (i.know?.known != null && !(i.know.concept_id in known)) known[i.know.concept_id] = i.know.known;
  }
  return { picks, known };
}

export function readbackInput(items: DiscoverItem[], answers: Answers, frame: string | null) {
  const label = (i: DiscoverItem) => domainLabel(i.topic) ?? i.topic_label;
  const terms = new Map(items.flatMap((i) => (i.know ? [[i.know.concept_id, i.know.label] as const] : [])));
  return {
    liked: items.filter((i) => answers.picks[i.id] === true).map(label),
    skipped: items.filter((i) => answers.picks[i.id] === false).map(label),
    known: Object.entries(answers.known).flatMap(([id, k]) => (k && terms.has(id) ? [terms.get(id)!] : [])),
    unknown: Object.entries(answers.known).flatMap(([id, k]) => (!k && terms.has(id) ? [terms.get(id)!] : [])),
    frame,
  };
}

interface CardProps {
  item: DiscoverItem;
  answers: Answers;
  onPick: (item: DiscoverItem, liked: boolean) => void;
  onKnow: (conceptId: string, known: boolean) => void;
}

function Card({ item, answers, onPick, onKnow }: CardProps) {
  const liked = answers.picks[item.id];
  const href = item.kind === "library" && item.content_id ? `/read/${item.content_id}` : item.url;
  const term = item.know;
  const known = term ? answers.known[term.concept_id] : undefined;
  return (
    <article className="discover-card" data-picked={liked === undefined ? undefined : liked ? "yes" : "no"}>
      <p className="discover-card__meta">
        <span className="discover-card__topic">{item.topic_label}</span> · {item.source}
        {item.format !== "article" && ` · ${item.format}`}
      </p>
      <h2 className="discover-card__title">
        <a href={href} target="_blank" rel="noopener noreferrer">
          {item.title}
        </a>
      </h2>
      {item.snippet && <p className="discover-card__snippet">{item.snippet}</p>}
      <div className="discover-card__answers" role="group" aria-label={`Would you read “${item.title}”?`}>
        <button type="button" className="answer" aria-pressed={liked === true} onClick={() => onPick(item, true)} disabled={liked !== undefined}>
          I'd read this
        </button>
        <button type="button" className="answer" aria-pressed={liked === false} onClick={() => onPick(item, false)} disabled={liked !== undefined}>
          Not for me
        </button>
      </div>
      {term && (
        <div className="discover-card__know" role="group" aria-label={`Do you know ${term.label}?`}>
          <span className="discover-card__ask">
            Know <mark className="discover-card__term">{term.label}</mark>?
          </span>
          <button type="button" className="answer answer--small" aria-pressed={known === true} onClick={() => onKnow(term.concept_id, true)} disabled={known !== undefined}>
            Yes
          </button>
          <button type="button" className="answer answer--small" aria-pressed={known === false} onClick={() => onKnow(term.concept_id, false)} disabled={known !== undefined}>
            Not really
          </button>
        </div>
      )}
    </article>
  );
}
