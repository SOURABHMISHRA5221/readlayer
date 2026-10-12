import { useEffect, useMemo, useState } from "react";

import { domainLabel, plural } from "../../lib/format";
import { personaParam, type PersonaKey } from "../../lib/personas";
import { profileApi, type Overview } from "../../lib/profileApi";
import { withParams } from "../../lib/router";
import { DOT_R, TILE_H, TILE_W, topicTiles, weekLine, type TopicTile } from "../../lib/weekMap";

type Load = { status: "loading" } | { status: "ready"; overview: Overview } | { status: "error" };

function tileLabel(t: TopicTile): string {
  const moved = t.rose ? `, ${t.rose} moved up this week` : "";
  return `${domainLabel(t.domain)}: ${plural(t.known, "idea")} on your map${moved}`;
}

/**
 * "Your map this week" in the library sidebar (Wide layout, decision 45): one small cluster of
 * dots per topic from the same overview as the profile's map, this week's risers ringed, and
 * the week in a line of text. Not interactive; the link opens the full map. A lazy chunk,
 * loaded from 960px up only.
 */
export default function WeekPanel({ persona }: { persona: PersonaKey | null }) {
  const [load, setLoad] = useState<Load>({ status: "loading" });
  useEffect(() => {
    const ctrl = new AbortController();
    setLoad({ status: "loading" });
    profileApi
      .overview(persona, ctrl.signal)
      .then((overview) => setLoad({ status: "ready", overview }))
      .catch(() => !ctrl.signal.aborted && setLoad({ status: "error" }));
    return () => ctrl.abort();
  }, [persona]);

  const tiles = useMemo(() => (load.status === "ready" ? topicTiles(load.overview) : []), [load]);
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
                  {d.rose && <circle cx={d.x} cy={d.y} r={DOT_R + 2.5} className="weekmap__ring" />}
                </g>
              ))}
            </svg>
            <p className="weekmap__topic">{domainLabel(t.domain)}</p>
            <p className="weekmap__meta tnum">
              {plural(t.known, "idea")}
              {t.rose > 0 && <span className="weekmap__up"> · +{t.rose} this week</span>}
            </p>
          </li>
        ))}
      </ul>
      <p className="weekmap__line">{weekLine(load.overview.nodes)}</p>
      <a className="weekmap__link" href={mapHref}>
        Open your map
      </a>
    </div>
  );
}
