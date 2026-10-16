import { useEffect, useRef, useState } from "react";

import { domainLabel } from "../../lib/format";
import { profileApi, type CalibrationNext } from "../../lib/profileApi";

type Answer = "explain" | "heard" | "none";

const ANSWERS: { key: Answer; label: string }[] = [
  { key: "explain", label: "Know it" },
  { key: "heard", label: "Heard of it" },
  { key: "none", label: "New to me" },
];

/**
 * Decision 68 K4: screen 2's "Quick check", apart from the taste cards above it. One term at a
 * time from the adaptive calibration (each answer moves the next one closer to the reader's
 * level); the answer is the reader's own word about a term, so it builds the starting map.
 * Skipping only hides the block: Finish (Start reading) is what ends onboarding.
 */
export function QuickCheck() {
  const [state, setState] = useState<CalibrationNext | null>(null);
  const [skipped, setSkipped] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const focusRef = useRef<HTMLElement | null>(null);
  const moved = useRef(false);

  useEffect(() => {
    let live = true;
    profileApi.calibrationNext().then(
      (next) => live && setState(next),
      () => live && setState(null),
    );
    return () => {
      live = false;
    };
  }, []);

  useEffect(() => {
    // After an answer, keep the keyboard where the reader is: the next term or the done line.
    if (moved.current) focusRef.current?.focus();
  }, [state]);

  if (skipped || state === null) return null;

  const answer = async (concept_id: string, a: Answer) => {
    setBusy(true);
    setError(null);
    try {
      await profileApi.calibrationAnswer(concept_id, a);
      moved.current = true;
      setState(await profileApi.calibrationNext());
    } catch {
      setError("That answer didn't save. Try once more.");
    } finally {
      setBusy(false);
    }
  };

  const item = state.done ? null : state.item;
  return (
    <section className="quickcheck" aria-labelledby="quickcheck-title">
      <div className="quickcheck__head">
        <h2 id="quickcheck-title" className="quickcheck__title">
          Quick check: do you know these?
        </h2>
        {item && (
          <button type="button" className="quickcheck__skip" onClick={() => setSkipped(true)}>
            Skip quick check
          </button>
        )}
      </div>
      {item ? (
        <div className="quickcheck__card">
          <p className="quickcheck__progress">
            {state.asked + 1} of {state.total}
          </p>
          <p className="quickcheck__term" tabIndex={-1} ref={(el) => void (focusRef.current = el)}>
            <span className="quickcheck__label">{item.label}</span>
            <span className="quickcheck__domain">{domainLabel(item.domain) ?? item.domain}</span>
          </p>
          <div className="quickcheck__answers" role="group" aria-label={`Do you know ${item.label}?`}>
            {ANSWERS.map((a) => (
              <button
                key={a.key}
                type="button"
                className="answer answer--small"
                disabled={busy}
                onClick={() => void answer(item.concept_id, a.key)}
              >
                {a.label}
              </button>
            ))}
          </div>
        </div>
      ) : (
        <p className="quickcheck__done" tabIndex={-1} role="status" ref={(el) => void (focusRef.current = el)}>
          Thanks, that's your starting map.
        </p>
      )}
      {error && (
        <p className="welcome__error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
