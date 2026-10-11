import { useId, useState, type RefObject } from "react";

import { ApiError } from "../../lib/api";
import { signOutUser } from "../../lib/auth";
import { COUNTRIES, COUNTRY_LABEL, type Country } from "../../lib/country";
import { domainLabel } from "../../lib/format";
import { onboardingApi, type ResolvedConcept, type ResolveResult } from "../../lib/onboardingApi";
import { DOMAINS, FIELD_FRAME, FIELDS, profileApi, type Domain, type Field, type Frame } from "../../lib/profileApi";
import { ChipGroup, DataLinks, MargoSays } from "./parts";

/** consent-v2 (decision 41): the inline consent on screen 1. v1 stays valid for older readers. */
export const CONSENT_VERSION = "consent-v2";
export const MAX_TEXT = 120;
export const MAX_TOPICS = 6; // screen 2 searches at most 6 topics
const FIELD_LABEL: Record<Field, string> = {
  software: "Software", finance: "Finance", commerce: "Commerce", law: "Law", science: "Science",
  medicine: "Medicine", design: "Design", teaching: "Teaching", other: "Something else",
}; // prettier-ignore

export interface MappedTopic {
  phrase: string;
  topic: Domain | null; // null = the reader dropped it
}

/** Screen 1's answers. The free text lives only here, in React state: never storage or the URL. */
export interface About {
  field: Field | null;
  /** Decision 50: prefilled from the browser's locale, stored only when Continue saves. */
  country: Country | null;
  topics: Domain[];
  text: string;
  resolvedFor: string | null; // the text the results below belong to
  concepts: ResolvedConcept[];
  mapped: MappedTopic[];
  unrecognised: string[];
}

export const EMPTY_ABOUT: About = {
  field: null, country: null, topics: [], text: "", resolvedFor: null, concepts: [], mapped: [], unrecognised: [],
}; // prettier-ignore

/** Interests sent to POST /v1/onboarding: chosen topics, mapped topics, resolved concepts' domains. */
export function chosenDomains(about: About): Domain[] {
  const mapped = about.mapped.flatMap((m) => (m.topic ? [m.topic] : []));
  return [...new Set([...about.topics, ...mapped, ...about.concepts.map((c) => c.domain)])];
}

export function frameFor(field: Field | null): Frame[] {
  const frame = field ? FIELD_FRAME[field] : undefined;
  return frame ? [frame] : [];
}

function withResult(about: About, text: string, r: ResolveResult): About {
  return {
    ...about,
    resolvedFor: text,
    concepts: r.concepts,
    mapped: r.topics.map((t) => ({ phrase: t.phrase, topic: t.topic })),
    unrecognised: r.unrecognised,
  };
}

interface Props {
  heading: RefObject<HTMLHeadingElement | null>;
  about: About;
  onChange: (next: About) => void;
  consented: boolean;
  onConsented: () => void;
  onSaved: () => void;
}

export function AboutScreen({ heading, about, onChange, consented, onConsented, onSaved }: Props) {
  const [agreed, setAgreed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const textId = useId();
  const text = about.text.trim();
  const ready = (consented || agreed) && about.field !== null && (about.topics.length > 0 || text.length > 0);

  const proceed = async () => {
    setBusy(true);
    setError(null);
    try {
      if (!consented) {
        await profileApi.consent(CONSENT_VERSION);
        onConsented();
      }
      if (text && about.resolvedFor !== text) {
        // Nothing is resolved or recorded before consent; the screen stays to show the matches.
        try {
          onChange(withResult(about, text, await onboardingApi.resolve(text)));
        } catch (e) {
          if (!(e instanceof ApiError) || e.status !== 429) throw e;
          onChange({ ...about, resolvedFor: text, concepts: [], mapped: [], unrecognised: [] });
          setError("That's enough matching for today. Pick topics above instead.");
        }
        return;
      }
      const interests = chosenDomains(about);
      if (!interests.length) {
        setError("Pick at least one topic.");
        return;
      }
      await profileApi.onboarding({
        field: about.field ?? "other",
        interests,
        thinks_in: frameFor(about.field),
        ...(about.country ? { country: about.country } : {}),
      });
      onSaved();
    } catch {
      setError("That didn't save. Try again.");
    } finally {
      setBusy(false);
    }
  };

  const toggleTopic = (d: Domain) =>
    onChange({
      ...about,
      topics: about.topics.includes(d)
        ? about.topics.filter((x) => x !== d)
        : about.topics.length < MAX_TOPICS
          ? [...about.topics, d]
          : about.topics,
    });
  const showResults = about.resolvedFor !== null && about.resolvedFor === text;

  return (
    <section className="welcome__panel" aria-labelledby="welcome-title">
      <MargoSays mood="idle">Pick a few, I'll find the rest.</MargoSays>
      <h1 id="welcome-title" className="welcome__title" ref={heading} tabIndex={-1}>
        Tell Margo about you
      </h1>
      <div className="welcome__body welcome__stack">
        <ChipGroup
          legend="What do you do?"
          hint="Analogies come from here."
          options={FIELDS.map((f) => ({ key: f, label: FIELD_LABEL[f] }))}
          selected={about.field ? [about.field] : []}
          onToggle={(f) => onChange({ ...about, field: f })}
        />
        <ChipGroup
          legend="Where do you read from?"
          hint="Most of your news comes from there."
          options={COUNTRIES.map((c) => ({ key: c, label: COUNTRY_LABEL[c] }))}
          selected={about.country ? [about.country] : []}
          onToggle={(c) => onChange({ ...about, country: c })}
        />
        <ChipGroup
          legend="What do you want to read about?"
          hint={`Pick up to ${MAX_TOPICS}.`}
          max={MAX_TOPICS}
          multiple
          options={DOMAINS.map((d) => ({ key: d, label: domainLabel(d) ?? d }))}
          selected={about.topics}
          onToggle={toggleTopic}
        />
        <div className="freetext">
          <label className="chips__legend" htmlFor={textId}>
            Anything else you follow? <span className="chips__hint">Optional.</span>
          </label>
          <input
            id={textId}
            className="freetext__input"
            type="text"
            autoComplete="off"
            maxLength={MAX_TEXT}
            placeholder="F1, startups, Indian politics"
            value={about.text}
            onChange={(e) => onChange({ ...about, text: e.target.value })}
          />
          {showResults && <Results about={about} onChange={onChange} />}
        </div>
        {!consented && (
          <div className="consent">
            <label className="consent__check">
              <input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} />
              <span>
                Gloss may keep what I read and answer here, only to choose which ideas to explain to me and how. What
                you type is matched to topics by our model and isn't stored.
              </span>
            </label>
            <a className="consent__link" href="/privacy" target="_blank" rel="noopener">
              What we store
            </a>
          </div>
        )}
      </div>
      {error && (
        <p className="welcome__error" role="alert">
          {error}
        </p>
      )}
      <div className="welcome__actions">
        {!consented && (
          <button type="button" className="btn btn--quiet" onClick={() => void signOutUser()}>
            Not now, sign out
          </button>
        )}
        <button type="button" className="btn btn--primary" disabled={!ready || busy} onClick={() => void proceed()}>
          Continue
        </button>
      </div>
      {!consented && <DataLinks />}
    </section>
  );
}

function Results({ about, onChange }: { about: About; onChange: (next: About) => void }) {
  const nothing = !about.concepts.length && !about.mapped.length && !about.unrecognised.length;
  return (
    <div className="matches" role="status">
      {nothing && <p className="matches__line">Nothing to match there. Your topics above are enough.</p>}
      {about.concepts.length > 0 && (
        <div className="matches__line">
          <span className="matches__label">Found</span>
          <ul className="matches__chips">
            {about.concepts.map((c) => (
              <li key={c.id} className="match-chip">
                {c.label}
                <button
                  type="button"
                  className="match-chip__remove"
                  aria-label={`Remove ${c.label}`}
                  onClick={() => onChange({ ...about, concepts: about.concepts.filter((x) => x.id !== c.id) })}
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      {about.mapped.map((m, i) => (
        <label key={m.phrase} className="matches__line">
          <span className="matches__phrase">{m.phrase}</span>
          <span aria-hidden="true">→</span>
          <select
            className="matches__select"
            aria-label={`Topic for ${m.phrase}`}
            value={m.topic ?? ""}
            onChange={(e) => {
              const topic = (e.target.value || null) as Domain | null;
              onChange({ ...about, mapped: about.mapped.map((x, j) => (j === i ? { ...x, topic } : x)) });
            }}
          >
            {DOMAINS.map((d) => (
              <option key={d} value={d}>
                {domainLabel(d) ?? d}
              </option>
            ))}
            <option value="">Don't use this</option>
          </select>
        </label>
      ))}
      {about.unrecognised.length > 0 && (
        <p className="matches__line matches__miss">Didn't recognise: {about.unrecognised.join(", ")}</p>
      )}
    </div>
  );
}
