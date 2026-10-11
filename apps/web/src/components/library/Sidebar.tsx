import { useEffect, useState } from "react";

import { domainLabel } from "../../lib/format";
import type { PersonaKey } from "../../lib/personas";
import { profileApi, type Goal } from "../../lib/profileApi";
import { ReadAnyLink } from "../ReadAnyLink";

function goalLine(g: Goal): string {
  if (g.type === "learning") return `${g.done} of ${g.total} ideas you know now`;
  const unit = g.metric === "minutes" ? "minutes" : "articles";
  const left = Math.max(0, g.total - g.done);
  return left ? `${g.done} ${unit} so far, ${left} to go this week` : `Done for this week: ${g.done} ${unit}`;
}

/** Right column on wide screens, below the feed on narrow ones (Design pass C5). */
export function Sidebar({
  persona, demo, topics, onTopic,
}: { persona: PersonaKey | null; demo: boolean; topics: string[]; onTopic: (d: string) => void }) {  // prettier-ignore
  const [goals, setGoals] = useState<Goal[] | null>(null);
  useEffect(() => {
    if (demo) return;
    const ctrl = new AbortController();
    profileApi.goals(ctrl.signal).then(setGoals).catch(() => setGoals([]));
    return () => ctrl.abort();
  }, [demo]);

  return (
    <aside className="side" aria-label="Your tools">
      <section className="side__block">
        <h2 className="side__h">Read any link</h2>
        <ReadAnyLink persona={persona} hideLabel id="anylink-side" />
      </section>
      <section className="side__block">
        <h2 className="side__h">Your goals</h2>
        {demo ? (
          <p className="side__note">Sign in with Google to set reading goals.</p>
        ) : goals === null ? (
          <p className="side__note">Loading…</p>
        ) : goals.length === 0 ? (
          <p className="side__note">
            No goals yet. <a href="/profile#goals-title">Add one on your profile</a>.
          </p>
        ) : (
          <ul className="goals-mini">
            {goals.slice(0, 3).map((g) => (
              <li key={g.id}>
                <p className="goals-mini__t">{g.type === "learning" ? `Understand ${g.label}` : g.label}</p>
                <p className="goals-mini__s">{goalLine(g)}</p>
                <progress max={1} value={g.fraction} aria-label={`${g.label}: ${goalLine(g)}`} />
              </li>
            ))}
          </ul>
        )}
      </section>
      {topics.length > 0 && (
        <section className="side__block">
          <h2 className="side__h">Topics for you</h2>
          <div className="chips-row">
            {topics.map((d) => (
              <button key={d} type="button" className="chip-btn" onClick={() => onTopic(d)}>
                {domainLabel(d)}
              </button>
            ))}
          </div>
        </section>
      )}
    </aside>
  );
}
