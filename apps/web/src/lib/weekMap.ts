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
const READY_PLACES = 2; // rings kept in a tile for what the reader is ready to learn next

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
  /** Ideas in this topic that moved up a level this week. (No total: the overview caps what it
   *  returns per topic, so its length is not the reader's count; the profile's cards have that.) */
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

/** A topic's `count` dots: every riser, then known ideas with up to READY_PLACES rings kept for
 *  what is ready to learn next (more of either when the other runs out). `queue` is sorted. */
function pick(queue: readonly OverviewNode[], count: number): OverviewNode[] {
  const risers = queue.filter((n) => n.rose_this_week).slice(0, count);
  const rest = queue.filter((n) => !n.rose_this_week);
  const known = rest.filter((n) => !n.ready);
  const ready = rest.filter((n) => n.ready);
  const room = count - risers.length;
  const rings = Math.min(ready.length, Math.max(Math.min(READY_PLACES, Math.floor(count / 3)), room - known.length));
  return [...risers, ...known.slice(0, room - rings), ...ready.slice(0, Math.max(0, rings))].slice(0, count);
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
  return queues.flatMap((queue, i) => pick(queue, taken[i] ?? 0));
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
