import { useEffect, useId, useState, type FormEvent } from "react";

import { ApiError } from "../../lib/api";
import { profileApi, type Goal } from "../../lib/profileApi";

interface Props {
  demo: boolean;
  refreshKey: number;
  onGoals: (goals: Goal[]) => void;
  onShowOnMap: (goal: Goal) => void;
}

function progressText(g: Goal): string {
  if (g.type === "habit") {
    const unit = g.metric === "minutes" ? "minutes" : "articles";
    return `${g.done} of ${g.total} ${unit} this week`;
  }
  return `${g.done} of ${g.total} idea${g.total === 1 ? "" : "s"} known`;
}

function message(e: unknown, fallback: string): string {
  return e instanceof ApiError && e.detail ? e.detail : fallback;
}

/** Reading goals (M7.5 §C): habit and learning goals with progress. Signed-in readers only. */
export function Goals({ demo, refreshKey, onGoals, onShowOnMap }: Props) {
  const [goals, setGoals] = useState<Goal[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    if (demo) return;
    const ctrl = new AbortController();
    profileApi
      .goals(ctrl.signal)
      .then((g) => {
        setGoals(g);
        onGoals(g);
      })
      .catch(() => !ctrl.signal.aborted && setFailed(true));
    return () => ctrl.abort();
  }, [demo, version, refreshKey, onGoals]);

  return (
    <section className="goals" aria-labelledby="goals-title">
      <h2 id="goals-title" className="profile__h2">
        Reading goals
      </h2>
      {demo ? (
        <p className="profile__note">Sign in with Google to set reading goals.</p>
      ) : (
        <>
          {failed && <p className="profile__note" role="status">Your goals didn't load. Try again in a moment.</p>}
          {goals && goals.length === 0 && <p className="profile__note">No goals yet. Add one below.</p>}
          {goals && goals.length > 0 && (
            <ul className="goals__list">
              {goals.map((g) => (
                <li key={g.id} className="goals__item">
                  <div className="goals__head">
                    <span className="goals__label">{g.type === "learning" ? `Understand ${g.label}` : g.label}</span>
                    <span className="goals__value">{progressText(g)}</span>
                  </div>
                  <progress className="goals__bar" max={1} value={g.fraction} aria-label={`${g.label}: ${progressText(g)}`} />
                  {g.paused && <p className="profile__note">Learning is paused, so reading isn't counting.</p>}
                  <div className="goals__actions">
                    {g.type === "learning" && (
                      <button type="button" className="btn btn--sm" onClick={() => onShowOnMap(g)}>
                        Show on map
                      </button>
                    )}
                    <button
                      type="button"
                      className="btn btn--sm"
                      aria-label={`Remove goal: ${g.label}`}
                      onClick={async () => {
                        await profileApi.deleteGoal(g.id).catch(() => undefined);
                        setVersion((v) => v + 1);
                      }}
                    >
                      Remove
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
          {(goals?.length ?? 0) < 5 && <AddGoal onAdded={() => setVersion((v) => v + 1)} />}
        </>
      )}
    </section>
  );
}

function AddGoal({ onAdded }: { onAdded: () => void }) {
  const id = useId();
  const [metric, setMetric] = useState<"articles" | "minutes">("articles");
  const [perWeek, setPerWeek] = useState(5);
  const [idea, setIdea] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");

  const addHabit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setNote("");
    try {
      await profileApi.addHabit(metric, perWeek);
      onAdded();
    } catch (err) {
      setNote(message(err, "That goal couldn't be added."));
    } finally {
      setBusy(false);
    }
  };

  const addLearning = async (e: FormEvent) => {
    e.preventDefault();
    if (!idea.trim()) return;
    setBusy(true);
    setNote("");
    try {
      await profileApi.addLearning(`understand ${idea.trim()}`);
      setIdea("");
      onAdded();
    } catch (err) {
      setNote(message(err, "That goal couldn't be added."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="goals__add">
      <form className="goals__form" onSubmit={addHabit}>
        <span className="goals__form-title">Read a little every week</span>
        <label htmlFor={`${id}-n`} className="visually-hidden">How many</label>
        <input id={`${id}-n`} className="goals__num" type="number" min={1} max={600} value={perWeek}
          onChange={(e) => setPerWeek(Number(e.target.value))} />
        <label htmlFor={`${id}-m`} className="visually-hidden">Unit</label>
        <select id={`${id}-m`} className="goals__select" value={metric}
          onChange={(e) => setMetric(e.target.value as "articles" | "minutes")}>
          <option value="articles">articles a week</option>
          <option value="minutes">minutes a week</option>
        </select>
        <button className="btn" type="submit" disabled={busy}>Add</button>
      </form>
      <form className="goals__form" onSubmit={addLearning}>
        <label htmlFor={`${id}-i`} className="goals__form-title">Understand an idea</label>
        <input id={`${id}-i`} className="goals__text" type="text" maxLength={100} value={idea}
          placeholder="e.g. insulin resistance" onChange={(e) => setIdea(e.target.value)} />
        <button className="btn" type="submit" disabled={busy || !idea.trim()}>Add</button>
      </form>
      <p className="profile__note" aria-live="polite">{note}</p>
    </div>
  );
}
