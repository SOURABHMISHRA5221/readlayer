import { useEffect, useState } from "react";

import { domainLabel } from "../../lib/format";
import { profileApi, type CalibrationSet } from "../../lib/profileApi";

type Answer = "explain" | "heard" | "none";

const ANSWERS: { key: Answer; label: string }[] = [
  { key: "explain", label: "Know it" },
  { key: "heard", label: "Heard of it" },
  { key: "none", label: "New to me" },
];

/**
 * Decision 68 K4/K4b: screen 2's "Quick check", apart from the taste cards above it. All six
 * terms at once, each answered in any order; the answer is the reader's own word about a term, so
 * it builds the starting map. Skipping only hides the block: Start reading ends onboarding.
 */
export function QuickCheck() {
  const [set, setSet] = useState<CalibrationSet | null>(null);
  // This screen's answers (a term answered before shows as answered, with no choice).
  const [chosen, setChosen] = useState<Record<string, Answer>>({});
  const [skipped, setSkipped] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    profileApi.calibrationSet().then(
      (s) => live && setSet(s),
      () => live && setSet(null),
    );
    return () => {
      live = false;
    };
  }, []);

  if (skipped || set === null || !set.items?.length) return null; // no terms (or an odd reply): no block

  const answered = (id: string) => id in chosen || set.items.find((i) => i.concept_id === id)!.answered;
  const allDone = set.items.every((i) => answered(i.concept_id));

  const answer = async (concept_id: string, a: Answer) => {
    if (answered(concept_id)) return;
    setChosen((cur) => ({ ...cur, [concept_id]: a }));
    setError(null);
    try {
      await profileApi.calibrationAnswer(concept_id, a);
    } catch {
      setChosen(({ [concept_id]: _, ...rest }) => rest);
      setError("That answer didn't save. Try once more.");
    }
  };

  return (
    <section className="quickcheck" aria-labelledby="quickcheck-title">
      <div className="quickcheck__head">
        <h2 id="quickcheck-title" className="quickcheck__title">
          Quick check: do you know these?
        </h2>
        {!allDone && (
          <button type="button" className="quickcheck__skip" onClick={() => setSkipped(true)}>
            Skip quick check
          </button>
        )}
      </div>
      <ul className="quickcheck__list">
        {set.items.map((item) => {
          const done = answered(item.concept_id);
          const pick = chosen[item.concept_id];
          return (
            <li key={item.concept_id} className="quickcheck__row" data-answered={done ? "yes" : undefined}>
              <p className="quickcheck__term">
                <span className="quickcheck__label">{item.label}</span>
                <span className="quickcheck__domain">{domainLabel(item.domain) ?? item.domain}</span>
              </p>
              <div className="quickcheck__answers" role="group" aria-label={`Do you know ${item.label}?`}>
                {ANSWERS.map((a) => (
                  <button
                    key={a.key}
                    type="button"
                    className="answer answer--small"
                    aria-pressed={pick === a.key}
                    aria-disabled={done}
                    onClick={() => void answer(item.concept_id, a.key)}
                  >
                    {a.label}
                  </button>
                ))}
              </div>
            </li>
          );
        })}
      </ul>
      {allDone && (
        <p className="quickcheck__done" role="status">
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
