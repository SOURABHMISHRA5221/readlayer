/**
 * "Your map this week" in the library (Wide layout, decision 45): one small cluster of dots per
 * topic, drawn from the same overview as the profile's map. Pure; the panel is
 * components/library/WeekPanel.tsx. The full map's layout (lib/mapLayout.ts) is built for a
 * 760px canvas and is not used here.
 */
import type { Band, Domain, Overview, OverviewNode } from "./profileApi";

export const TILE_W = 96;
export const TILE_H = 64;
export const DOT_R = 4;
const PER_TOPIC = 8;
const MAX_DOTS = 24;
const GOLDEN = 2.399963;
const SPREAD = 10.5; // spiral step: the two closest dots end up just over a diameter apart
const NAMED = 3;

type MapData = Pick<Overview, "domains" | "nodes">;

export interface TileDot {
  id: string;
  x: number;
  y: number;
  band: Band;
  ready: boolean;
  rose: boolean;
}

export interface TopicTile {
  domain: Domain;
  /** Ideas at "heard of" or above on the reader's map in this topic. */
  known: number;
  rose: number;
  dots: TileDot[];
}

/** This week's risers, then known ideas by weight, then ready-to-learn ones; ids break ties. */
function byImportance(a: OverviewNode, b: OverviewNode): number {
  return (
    Number(b.rose_this_week) - Number(a.rose_this_week) ||
    Number(a.ready) - Number(b.ready) ||
    b.weight - a.weight ||
    a.id.localeCompare(b.id)
  );
}

/**
 * The ideas the mini-map draws: every riser first (a riser is never dropped for an idea that
 * didn't move), then the rest shared evenly between topics, up to `perTopic` each and `max` in
 * all. Returned in the overview's topic order, most important first within a topic.
 */
export function miniMapNodes(overview: MapData, perTopic = PER_TOPIC, max = MAX_DOTS): OverviewNode[] {
  const queues = overview.domains.map((d) => overview.nodes.filter((n) => n.domain === d).sort(byImportance));
  const taken = queues.map(() => 0);
  let total = 0;
  queues.forEach((queue, i) => {
    const risers = Math.min(perTopic, queue.filter((n) => n.rose_this_week).length, max - total);
    taken[i] = risers;
    total += risers;
  });
  for (let level = 1; level <= perTopic && total < max; level++) {
    queues.forEach((queue, i) => {
      if ((taken[i] ?? 0) < level && (taken[i] ?? 0) < queue.length && total < max) {
        taken[i] = (taken[i] ?? 0) + 1;
        total += 1;
      }
    });
  }
  return queues.flatMap((queue, i) => queue.slice(0, taken[i]));
}

/** `count` dots on a sunflower spiral in a TILE_W × TILE_H box, the first in the middle. */
export function clusterDots(count: number): { x: number; y: number }[] {
  return Array.from({ length: count }, (_, i) => {
    const radius = SPREAD * Math.sqrt(i);
    const angle = i * GOLDEN;
    return { x: TILE_W / 2 + Math.cos(angle) * radius * 1.3, y: TILE_H / 2 + Math.sin(angle) * radius * 0.82 };
  });
}

/** One tile per topic that has ideas, in the overview's order. */
export function topicTiles(overview: MapData): TopicTile[] {
  const picked = miniMapNodes(overview);
  return overview.domains.flatMap((domain) => {
    const mine = overview.nodes.filter((n) => n.domain === domain);
    const shown = picked.filter((n) => n.domain === domain);
    if (!shown.length) return [];
    const at = clusterDots(shown.length);
    return [
      {
        domain,
        known: mine.filter((n) => !n.ready).length,
        rose: mine.filter((n) => n.rose_this_week).length,
        dots: shown.map((n, i) => ({ id: n.id, x: at[i]?.x ?? 0, y: at[i]?.y ?? 0, band: n.band, ready: n.ready, rose: n.rose_this_week })),
      },
    ];
  });
}

/** The week in words, under the tiles: the same information for anyone who can't see them. */
export function weekLine(nodes: readonly OverviewNode[]): string {
  const rose = nodes.filter((n) => n.rose_this_week).map((n) => n.label);
  if (!rose.length) return "Nothing moved up yet this week";
  const named = rose.slice(0, NAMED);
  const rest = rose.length - named.length;
  const list = rest
    ? `${named.join(", ")} and ${rest} more`
    : named.length > 1
      ? `${named.slice(0, -1).join(", ")} and ${named[named.length - 1]}`
      : named[0];
  return `${rose.length} ${rose.length === 1 ? "idea" : "ideas"} moved up this week: ${list}`;
}
