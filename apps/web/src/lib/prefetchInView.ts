import { MARK_CLASS, markId, type CardAnnotation, type FrameChoice } from "@readlayer/annotator";

import { loadExplanation, PREFETCH_TOP } from "./explanations";
import type { PersonaKey } from "./personas";

// Loaded on demand for signed-in consumers only (keeps the main bundle in its budget).

/** Decision 67 L3: notes prefetched per page in all (the top 3 included), and at once. */
export const PREFETCH_MAX = 10;
export const PREFETCH_IN_FLIGHT = 2;

export interface Prefetcher {
  /** Ask for one note; ignored once seen, or past the page's total. */
  request(id: string): void;
  readonly started: number;
}

/**
 * A queue that starts at most `max` loads in all and `inFlight` at a time, each id once. Pure:
 * `load` does the work, so the limits are tested without a DOM or network.
 */
export function makePrefetcher(
  load: (id: string) => Promise<unknown>,
  max = PREFETCH_MAX,
  inFlight = PREFETCH_IN_FLIGHT,
  /** Ids already started on this page: shared, so a notes refresh doesn't restart the count. */
  seen: Set<string> = new Set(),
): Prefetcher {
  const queue: string[] = [];
  let running = 0;
  let started = seen.size;
  const pump = () => {
    while (running < inFlight && queue.length) {
      const id = queue.shift()!;
      running++;
      load(id)
        .catch(() => undefined)
        .finally(() => {
          running--;
          pump();
        });
    }
  };
  return {
    request(id) {
      if (seen.has(id) || started >= max) return;
      seen.add(id);
      started++;
      queue.push(id);
      pump();
    },
    get started() {
      return started;
    },
  };
}

/**
 * Signed-in consumers only (demo consumers keep the top 3: their daily caps are for clicks):
 * notes whose mark comes within one screen of the viewport are prefetched, up to PREFETCH_MAX
 * per page with the top 3, PREFETCH_IN_FLIGHT at a time. Returns the cleanup.
 */
export function prefetchInView(
  root: HTMLElement,
  contentId: string,
  persona: PersonaKey | null,
  annotations: readonly CardAnnotation[],
  /** This article's started ids (the top 3 included), kept by the host across refreshes. */
  seen: Set<string> = new Set(),
  /** The page's analogy frame (decision 67 A4): prefetch in the one the reader chose. */
  frame: () => FrameChoice = () => "pick",
): () => void {
  if (persona !== null || typeof IntersectionObserver === "undefined") return () => undefined;
  const byId = new Map(annotations.filter((a) => a.kind === "span").map((a) => [a.id, a]));
  const top = [...annotations]
    .filter((a) => a.kind === "span")
    .sort((a, b) => b.score - a.score)
    .slice(0, PREFETCH_TOP)
    .map((a) => a.id);
  for (const id of top) seen.add(id); // prefetched on load: they count toward the page's total
  const queue = makePrefetcher(
    (id) => loadExplanation(contentId, persona, byId.get(id)!, true, frame()),
    PREFETCH_MAX,
    PREFETCH_IN_FLIGHT,
    seen,
  );
  if (queue.started >= PREFETCH_MAX) return () => undefined;
  const view = root.ownerDocument.defaultView;
  const observer = new IntersectionObserver(
    (entries) => {
      for (const e of entries) {
        const id = e.isIntersecting ? markId(e.target) : null;
        if (id && byId.has(id)) queue.request(id);
        if (queue.started >= PREFETCH_MAX) observer.disconnect();
      }
    },
    { rootMargin: `${view?.innerHeight ?? 800}px 0px` },
  );
  root.querySelectorAll(`.${MARK_CLASS}`).forEach((m) => observer.observe(m));
  return () => observer.disconnect();
}
