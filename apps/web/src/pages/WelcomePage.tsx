import { useEffect, useRef, useState, type ReactNode } from "react";

import { Segmented } from "../components/Segmented";
import { Wordmark } from "../components/Wordmark";
import { api, type ContentSummary } from "../lib/api";
import { signOutUser } from "../lib/auth";
import { domainLabel } from "../lib/format";
import {
  DOMAINS,
  FIELD_FRAME,
  FIELDS,
  FRAMES,
  profileApi,
  type CalibrationNext,
  type Domain,
  type Field,
  type Frame,
  type Level,
} from "../lib/profileApi";
import { navigate } from "../lib/router";
import "../styles/welcome.css";

/** Consent → onboarding → calibration for a signed-in reader (DESIGN §4, §11.4; M7). */
export const CONSENT_VERSION = "consent-v1";
const LEVELS: { key: Level; label: string }[] = [
  { key: "new", label: "New to it" },
  { key: "some", label: "Some" },
  { key: "comfortable", label: "Comfortable" },
  { key: "expert", label: "Expert" },
];
const FIELD_LABEL: Record<Field, string> = {
  software: "Software", finance: "Finance", commerce: "Commerce", law: "Law", science: "Science",
  medicine: "Medicine", design: "Design", teaching: "Teaching", other: "Something else",
}; // prettier-ignore
const STEPS = ["consent", "field", "interests", "comfort", "frames", "liked", "calibration"] as const;
type Step = (typeof STEPS)[number];

export default function WelcomePage() {
  const [step, setStep] = useState<Step | "loading">("loading");
  const [field, setField] = useState<Field | null>(null);
  const [interests, setInterests] = useState<Domain[]>([]);
  const [comfort, setComfort] = useState<Partial<Record<Domain, Level>>>({});
  const [frames, setFrames] = useState<Frame[]>([]);
  const [liked, setLiked] = useState<ContentSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const heading = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    document.title = "Welcome · ReadLayer";
    profileApi
      .profile(null)
      .then((p) => {
        const s = p.onboarding.step;
        setStep(s === "consent" ? "consent" : s === "calibration" ? "calibration" : s === "done" ? "calibration" : "field");
      })
      .catch(() => setStep("consent"));
  }, []);

  // Each step change moves focus to its heading, so keyboard and screen-reader users start there.
  useEffect(() => {
    if (step !== "loading") heading.current?.focus();
  }, [step]);

  const index = step === "loading" ? 0 : STEPS.indexOf(step);
  const go = (next: Step) => {
    setError(null);
    setStep(next);
  };
  const run = async (work: () => Promise<void>, failure: string) => {
    setBusy(true);
    setError(null);
    try {
      await work();
    } catch {
      setError(failure);
    } finally {
      setBusy(false);
    }
  };

  const finish = () => {
    window.dispatchEvent(new Event("rl:onboarding-changed"));
    navigate("/", { replace: true });
  };

  if (step === "loading") {
    return <Shell index={0}>{null}</Shell>;
  }

  return (
    <Shell index={index}>
      {step === "consent" && (
        <Panel
          heading={heading}
          eyebrow="Before you start"
          title="What ReadLayer keeps about your reading"
          actions={
            <>
              <button type="button" className="btn" onClick={() => void signOutUser()}>
                No thanks, sign out
              </button>
              <button
                type="button"
                className="btn btn--primary"
                disabled={busy}
                onClick={() => run(async () => { await profileApi.consent(CONSENT_VERSION); go("field"); }, "That didn't save. Try again.")}
              >
                I agree, continue
              </button>
            </>
          }
          error={error}
        >
          <ul className="welcome__facts">
            <li>
              <strong>What we keep.</strong> What you open, how long paragraphs stay on screen, the
              notes you mark as known or unclear, your answers on the next few screens and your
              settings. Never the text you select or copy.
            </li>
            <li>
              <strong>Why.</strong> Only to choose which ideas to explain to you and how, so the notes
              thin out as you learn.
            </li>
            <li>
              <strong>What we never do.</strong> Send your email, name or reading history to an AI
              model, or sell or share your data. To write an explanation, the AI model gets the
              article passage, your level for that idea, your analogy field and preferred length:
              nothing that says who you are.
            </li>
            <li>
              <strong>Your control.</strong> Export or delete everything at any time, here or from the
              account menu, or pause learning on your profile page.
            </li>
          </ul>
          <DataLinks />
        </Panel>
      )}

      {step === "field" && (
        <Panel
          heading={heading}
          eyebrow="1 of 5"
          title="What do you do?"
          lede="It helps us pick analogies you'll recognise."
          actions={<NextBack onBack={null} onNext={() => go("interests")} disabled={!field} />}
        >
          <Choices
            label="Your field"
            options={FIELDS.map((f) => ({ key: f, label: FIELD_LABEL[f] }))}
            selected={field ? [field] : []}
            onToggle={(f) => {
              setField(f);
              const suggested = FIELD_FRAME[f];
              setFrames(suggested ? [suggested] : []);
            }}
          />
        </Panel>
      )}

      {step === "interests" && (
        <Panel
          heading={heading}
          eyebrow="2 of 5"
          title="What do you want to read about?"
          lede="Pick any. We'll start with these."
          actions={<NextBack onBack={() => go("field")} onNext={() => go("comfort")} disabled={!interests.length} />}
        >
          <Choices
            label="Topics"
            multiple
            options={DOMAINS.map((d) => ({ key: d, label: domainLabel(d) ?? d }))}
            selected={interests}
            onToggle={(d) => setInterests((cur) => (cur.includes(d) ? cur.filter((x) => x !== d) : [...cur, d]))}
          />
        </Panel>
      )}

      {step === "comfort" && (
        <Panel
          heading={heading}
          eyebrow="3 of 5"
          title="How comfortable are you with each?"
          lede="A rough guess is fine. A few quick questions will fine-tune it."
          actions={<NextBack onBack={() => go("interests")} onNext={() => go("frames")} disabled={interests.some((d) => !comfort[d])} />}
        >
          <div className="welcome__comfort">
            {interests.map((d) => (
              <Segmented
                key={d}
                label={domainLabel(d) ?? d}
                options={LEVELS}
                value={comfort[d] ?? ("" as Level)}
                onChange={(level) => setComfort((cur) => ({ ...cur, [d]: level }))}
              />
            ))}
          </div>
        </Panel>
      )}

      {step === "frames" && (
        <Panel
          heading={heading}
          eyebrow="4 of 5"
          title="Explain things in terms of…"
          lede="Pick up to three. Analogies only ever come from these."
          actions={<NextBack onBack={() => go("comfort")} onNext={() => go("liked")} />}
        >
          <Choices
            label="Analogy fields"
            multiple
            max={3}
            options={FRAMES.map((f) => ({ key: f, label: f[0]!.toUpperCase() + f.slice(1) }))}
            selected={frames}
            onToggle={(f) => setFrames((cur) => (cur.includes(f) ? cur.filter((x) => x !== f) : cur.length < 3 ? [...cur, f] : cur))}
          />
        </Panel>
      )}

      {step === "liked" && (
        <Panel
          heading={heading}
          eyebrow="5 of 5 · optional"
          title="Anything here you've enjoyed?"
          lede="Pick up to three articles from the library, or skip."
          error={error}
          actions={
            <NextBack
              onBack={() => go("frames")}
              nextLabel={liked.length ? "Continue" : "Skip"}
              disabled={busy}
              onNext={() =>
                run(async () => {
                  await profileApi.onboarding({
                    field: field ?? "other",
                    interests,
                    comfort,
                    thinks_in: frames,
                    liked_content_ids: liked.map((a) => a.id),
                  });
                  go("calibration");
                }, "That didn't save. Try again.")
              }
            />
          }
        >
          <LikedPicker picked={liked} onChange={setLiked} />
        </Panel>
      )}

      {step === "calibration" && <Calibration heading={heading} onDone={finish} />}
    </Shell>
  );
}

/** Export and delete work before consent too (the API keeps them open), so leaving is easy. */
function DataLinks() {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const deleteButton = useRef<HTMLButtonElement>(null);
  const exportData = async () => {
    setBusy(true);
    try {
      const blob = await api.exportMe();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "readlayer-export.json";
      a.click();
      URL.revokeObjectURL(a.href);
    } catch {
      setMessage("The export didn't download. Try again.");
    } finally {
      setBusy(false);
    }
  };
  const deleteAll = async () => {
    setBusy(true);
    try {
      await api.deleteMe();
      await signOutUser();
    } catch {
      setMessage("We couldn't delete your account. Try again.");
      setBusy(false);
    }
  };
  return (
    <div className="welcome__data">
      <button type="button" className="btn btn--link" onClick={() => void exportData()} disabled={busy}>
        Export my data
      </button>
      {!confirming ? (
        <button type="button" ref={deleteButton} className="btn btn--link btn--link-danger" onClick={() => setConfirming(true)} disabled={busy}>
          Delete my account
        </button>
      ) : (
        <span
          className="welcome__confirm"
          role="group"
          aria-label="Confirm delete"
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              setConfirming(false);
              requestAnimationFrame(() => deleteButton.current?.focus());
            }
          }}
        >
          <span>Delete your account and everything with it?</span>
          <button type="button" className="btn" autoFocus onClick={() => setConfirming(false)} disabled={busy}>
            Cancel
          </button>
          <button type="button" className="btn btn--danger" onClick={() => void deleteAll()} disabled={busy}>
            Delete
          </button>
        </span>
      )}
      {message && (
        <p className="welcome__error" role="alert">
          {message}
        </p>
      )}
    </div>
  );
}

function Shell({ index, children }: { index: number; children: ReactNode }) {
  return (
    <div className="welcome">
      <header className="welcome__bar">
        <Wordmark />
        <ol className="welcome__dots" aria-label="Progress">
          {STEPS.map((s, i) => (
            <li key={s} data-state={i < index ? "done" : i === index ? "current" : "todo"}>
              <span className="visually-hidden">
                Step {i + 1} of {STEPS.length}
                {i === index ? " (current)" : i < index ? " (done)" : ""}
              </span>
            </li>
          ))}
        </ol>
      </header>
      <main className="welcome__main">{children}</main>
    </div>
  );
}

interface PanelProps {
  heading: React.RefObject<HTMLHeadingElement | null>;
  eyebrow: string;
  title: string;
  lede?: string;
  children: ReactNode;
  actions?: ReactNode;
  error?: string | null;
}

function Panel({ heading, eyebrow, title, lede, children, actions, error }: PanelProps) {
  return (
    <section className="welcome__panel" aria-labelledby="welcome-title">
      <p className="eyebrow">{eyebrow}</p>
      <h1 id="welcome-title" className="welcome__title" ref={heading} tabIndex={-1}>
        {title}
      </h1>
      {lede && <p className="welcome__lede">{lede}</p>}
      <div className="welcome__body">{children}</div>
      {error && (
        <p className="welcome__error" role="alert">
          {error}
        </p>
      )}
      {actions && <div className="welcome__actions">{actions}</div>}
    </section>
  );
}

function NextBack({
  onBack,
  onNext,
  disabled = false,
  nextLabel = "Continue",
}: {
  onBack: (() => void) | null;
  onNext: () => void;
  disabled?: boolean;
  nextLabel?: string;
}) {
  return (
    <>
      {onBack && (
        <button type="button" className="btn" onClick={onBack}>
          Back
        </button>
      )}
      <button type="button" className="btn btn--primary" onClick={onNext} disabled={disabled}>
        {nextLabel}
      </button>
    </>
  );
}

interface ChoicesProps<K extends string> {
  label: string;
  options: { key: K; label: string }[];
  selected: K[];
  onToggle: (key: K) => void;
  multiple?: boolean;
  max?: number;
}

/** Big, tappable choices: checkboxes (multiple) or radios, drawn as cards. */
function Choices<K extends string>({ label, options, selected, onToggle, multiple = false, max }: ChoicesProps<K>) {
  return (
    <fieldset className="choices">
      <legend className="visually-hidden">
        {label}
        {max ? ` (up to ${max})` : ""}
      </legend>
      {options.map((o) => {
        const on = selected.includes(o.key);
        return (
          <label key={o.key} className="choice" data-on={on}>
            <input
              type={multiple ? "checkbox" : "radio"}
              name={label}
              checked={on}
              onChange={() => onToggle(o.key)}
              disabled={!on && max !== undefined && selected.length >= max}
            />
            <span>{o.label}</span>
          </label>
        );
      })}
    </fieldset>
  );
}

function LikedPicker({ picked, onChange }: { picked: ContentSummary[]; onChange: (v: ContentSummary[]) => void }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<ContentSummary[]>([]);
  useEffect(() => {
    const ctrl = new AbortController();
    const t = setTimeout(() => {
      api
        .library(query, null, "balanced", ctrl.signal)
        .then((rows) => setResults(rows.slice(0, 8)))
        .catch(() => undefined);
    }, 200);
    return () => {
      clearTimeout(t);
      ctrl.abort();
    };
  }, [query]);
  const toggle = (a: ContentSummary) =>
    onChange(picked.some((p) => p.id === a.id) ? picked.filter((p) => p.id !== a.id) : picked.length < 3 ? [...picked, a] : picked);
  return (
    <div className="liked">
      <label className="liked__search">
        <span className="visually-hidden">Search the library</span>
        <input type="search" placeholder="Search the library" value={query} onChange={(e) => setQuery(e.target.value)} />
      </label>
      <ul className="liked__list">
        {results.map((a) => {
          const on = picked.some((p) => p.id === a.id);
          return (
            <li key={a.id}>
              <button type="button" className="liked__item" aria-pressed={on} onClick={() => toggle(a)} disabled={!on && picked.length >= 3}>
                <span className="liked__title">{a.title}</span>
                <span className="liked__site">{a.site}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function Calibration({ heading, onDone }: { heading: React.RefObject<HTMLHeadingElement | null>; onDone: () => void }) {
  const [next, setNext] = useState<CalibrationNext | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = () =>
    profileApi
      .calibrationNext()
      .then((n) => (n.done ? onDone() : setNext(n)))
      .catch(() => setError("We couldn't load the next question."));

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (next?.item) heading.current?.focus();
  }, [next, heading]);

  const answer = async (a: "explain" | "heard" | "none") => {
    if (!next?.item) return;
    setBusy(true);
    try {
      const r = await profileApi.calibrationAnswer(next.item.concept_id, a);
      if (r.done) onDone();
      else await load();
    } catch {
      setError("That answer didn't save. Try again.");
    } finally {
      setBusy(false);
    }
  };

  const skip = async () => {
    setBusy(true);
    await profileApi.calibrationSkip().catch(() => undefined);
    onDone();
  };

  return (
    <section className="welcome__panel" aria-labelledby="welcome-title">
      <p className="eyebrow">
        Quick check · {next ? Math.min(next.asked + 1, next.total) : 1} of {next?.total ?? 8}
      </p>
      <h1 id="welcome-title" className="welcome__title welcome__term" ref={heading} tabIndex={-1}>
        {next?.item ? next.item.label : "…"}
      </h1>
      <p className="welcome__lede">
        {next?.item ? `${domainLabel(next.item.domain) ?? next.item.domain}. How well do you know it?` : ""}
      </p>
      <div className="welcome__answers" role="group" aria-label="How well do you know it?">
        <button type="button" className="btn btn--answer" disabled={busy || !next?.item} onClick={() => answer("explain")}>
          I could explain it
        </button>
        <button type="button" className="btn btn--answer" disabled={busy || !next?.item} onClick={() => answer("heard")}>
          I've heard of it
        </button>
        <button type="button" className="btn btn--answer" disabled={busy || !next?.item} onClick={() => answer("none")}>
          New to me
        </button>
      </div>
      {error && (
        <p className="welcome__error" role="alert">
          {error}
        </p>
      )}
      <div className="welcome__actions">
        <button type="button" className="btn btn--quiet" onClick={() => void skip()} disabled={busy}>
          Skip the rest
        </button>
      </div>
    </section>
  );
}
