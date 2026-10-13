import { useEffect, useMemo, useState } from "react";

import { domainLabel, plural } from "../../lib/format";
import { personaParam, type PersonaKey } from "../../lib/personas";
import { profileApi, type Overview } from "../../lib/profileApi";
import { withParams } from "../../lib/router";
import { DOT_R, RING_R, TILE_H, TILE_W, topicTiles, weekLine, type Move, type TopicTile } from "../../lib/weekMap";

type Load = { status: "loading" } | { status: "ready"; overview: Overview; moved: Move[] } | { status: "error" };

function tileLabel(t: TopicTile): string {
  return `${domainLabel(t.domain)}: ${t.rose ? `${plural(t.rose, "idea")} moved up this week` : "no change this week"}`;
}

/**
 * "Your map this week" in the library sidebar (Wide layout, decision 45): one small cluster of
 * dots per topic from the same overview as the profile's map, and the week in a line of text.
 * The overview only carries a topic's top ideas, so what rose this week is read from the
 * profile's own list (the same one its "This week" shows); neither answer alone is shown as the
 * week. Not interactive; the link opens the full map. A lazy chunk, loaded from 961px up only.
 */
export default function WeekPanel({ persona }: { persona: PersonaKey | null }) {
  const [load, setLoad] = useState<Load>({ status: "loading" });
  useEffect(() => {
    const ctrl = new AbortController();
    setLoad({ status: "loading" });
    Promise.all([profileApi.overview(persona, ctrl.signal), profileApi.profile(persona, ctrl.signal)])
      .then(([overview, profile]) => setLoad({ status: "ready", overview, moved: profile.week.moved_up }))
      .catch(() => !ctrl.signal.aborted && setLoad({ status: "error" }));
    return () => ctrl.abort();
  }, [persona]);

  const tiles = useMemo(() => (load.status === "ready" ? topicTiles(load.overview, load.moved) : []), [load]);
  const mapHref = `${withParams(new URL("/profile", window.location.origin), { persona: personaParam(persona) })}#kmap-title`;

  if (load.status === "loading") return <div className="skeleton weekmap__skeleton" role="status" aria-label="Loading your map" />; // as Sidebar's MapSkeleton
  if (load.status === "error") {
    return (
      <p className="side__note" role="status">
        Your map didn't load.
      </p>
    );
  }
  if (!tiles.length) return <p className="side__note">Your map fills in as you read.</p>;
  return (
    <div className="weekmap">
      <ul className="weekmap__tiles">
        {tiles.map((t) => (
          <li key={t.domain} className="weekmap__tile">
            <svg width={TILE_W} height={TILE_H} viewBox={`0 0 ${TILE_W} ${TILE_H}`} role="img" aria-label={tileLabel(t)}>
              {t.dots.map((d) => (
                <g key={d.id} className="weekmap__dot" data-band={d.band} data-ready={d.ready || undefined}>
                  <circle cx={d.x} cy={d.y} r={DOT_R} />
                  {d.rose && <circle cx={d.x} cy={d.y} r={RING_R} className="weekmap__ring" />}
                </g>
              ))}
            </svg>
            <p className="weekmap__topic">{domainLabel(t.domain)}</p>
            {t.rose > 0 && <p className="weekmap__up tnum">+{t.rose} this week</p>}
          </li>
        ))}
      </ul>
      <p className="weekmap__line">{weekLine(load.moved)}</p>
      <ul className="weekmap__key" aria-label="Key">
        <li>
          <span className="weekmap__mark" aria-hidden="true" /> We think you know
        </li>
        <li>
          <span className="weekmap__mark" data-kind="ready" aria-hidden="true" /> Ready next
        </li>
        <li>
          <span className="weekmap__mark" data-kind="rose" aria-hidden="true" /> Moved up
        </li>
      </ul>
      <a className="weekmap__link" href={mapHref}>
        Open your map
      </a>
    </div>
  );
}
