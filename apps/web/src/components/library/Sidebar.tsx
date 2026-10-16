import { lazy, Suspense, useEffect, useState } from "react";

import { useMediaQuery } from "../../hooks/useMediaQuery";
import { domainLabel } from "../../lib/format";
import { personaOf, type PersonaKey } from "../../lib/personas";
import { profileApi, type Goal } from "../../lib/profileApi";
import { Quiet } from "../Quiet";
import { ReadAnyLink } from "../ReadAnyLink";

const MapSkeleton = () => <div className="skeleton weekmap__skeleton" role="status" aria-label="Loading your map" />;

function goalLine(g: Goal): string {
  if (g.type === "learning") return `${g.done} of ${g.total} ideas you know now`;
  const unit = g.metric === "minutes" ? "minutes" : "articles";
  const left = Math.max(0, g.total - g.done);
  return left ? `${g.done} ${unit} so far, ${left} to go this week` : `Done for this week: ${g.done} ${unit}`;
}

// Its own chunk, and only where there is a sidebar column to hold it: phones make no extra
// request (Wide layout, decision 45).
const WeekPanel = lazy(() => import("./WeekPanel"));
const SIDE_QUERY = "(min-width: 961px)"; // beside the feed (library.css stacks it at 960px)

/**
 * Beside the feed on wide screens, below it on narrow ones (Design pass C5). Two groups (Wide
 * layout): tools, then the reader's own map and goals. They stack in one column up to 1439px
 * and sit side by side from 1440px (the third column); DOM order is the visual order either way.
 */
export function Sidebar({
  persona, demo, topics, settled, onTopic,
}: { persona: PersonaKey | null; demo: boolean; topics: string[]; settled: boolean; onTopic: (d: string) => void }) {  // prettier-ignore
  const [goals, setGoals] = useState<Goal[] | null>(null);
  const wide = useMediaQuery(SIDE_QUERY);
  useEffect(() => {
    if (demo) return;
    const ctrl = new AbortController();
    profileApi.goals(ctrl.signal).then(setGoals).catch(() => setGoals([]));
    return () => ctrl.abort();
  }, [demo]);

  return (
    <aside className="side" aria-label="Your tools">
      <div className="side__col">
        <section className="side__block">
          <h2 className="side__h">Open any link</h2>
          <ReadAnyLink persona={persona} hideLabel id="anylink-side" />
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
      </div>
      <div className="side__col">
        {wide && (
          <section className="side__block side__block--week">
            <h2 className="side__h">{persona ? `${personaOf(persona).label}'s map this week` : "Your map this week"}</h2>
            {/* Asked for once the library has answered: a new reader's first requests each create
                their user record, and one more at that moment only makes them queue. */}
            {settled ? (
              <Quiet fallback={<p className="side__note">Your map didn't load.</p>}>
                <Suspense fallback={<MapSkeleton />}>
                  <WeekPanel persona={persona} />
                </Suspense>
              </Quiet>
            ) : (
              <MapSkeleton />
            )}
          </section>
        )}
        <section className="side__block">
          <h2 className="side__h">Your goals</h2>
          {demo ? (
            <p className="side__note">Sign in with Google to set goals.</p>
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
      </div>
    </aside>
  );
}
