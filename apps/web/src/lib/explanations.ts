import { MARK_CLASS, markId, type CardAnnotation, type Explanation } from "@readlayer/annotator";

import { api } from "./api";
import type { PersonaKey } from "./personas";

/**
 * Verified explanations for span and paragraph cards (DESIGN §7). One request per (persona, article, note)
 * per page session; the top spans are fetched as soon as the annotations arrive, so their
 * first hover fills at once, and the rest load when their card opens. A failed load is
 * forgotten so the next open tries again; the card shows the definition meanwhile.
 */
export const PREFETCH_TOP = 3;

const cache = new Map<string, Promise<Explanation>>();

const keyOf = (persona: PersonaKey | null, contentId: string, annotationId: string, shift = 0) =>
  `${persona ?? "me"}|${contentId}|${annotationId}|${shift}`;

const toExplanation = (r: Awaited<ReturnType<typeof api.explain>>): Explanation => ({
  id: r.id,
  kind: r.kind,
  background: r.background,
  author_says: r.author_says,
  analogy_domain: r.analogy_domain,
  band: r.band,
  can_simpler: r.can_simpler,
  can_deeper: r.can_deeper,
});

export function loadExplanation(
  contentId: string,
  persona: PersonaKey | null,
  annotation: CardAnnotation,
  prefetch = false,
): Promise<Explanation> {
  const key = keyOf(persona, contentId, annotation.id);
  const hit = cache.get(key);
  if (hit) return hit;
  // Paragraph markers are explained by paragraph; spans by their demand id.
  const target =
    annotation.kind === "paragraph" ? { paragraph_id: annotation.paragraph_id } : { demand_id: annotation.id };
  const pending = api.explain(contentId, target, persona).then((r) => {
    // A capped prefetch isn't kept: a later click asks again (decision 67 L3).
    if (prefetch && r.capped && cache.get(key) === pending) cache.delete(key);
    return toExplanation(r);
  });
  cache.set(key, pending);
  pending.catch(() => cache.delete(key));
  return pending;
}

/** "Say it simpler" / "Go deeper": only on click, never prefetched (Design pass A3). */
export function loadShifted(
  contentId: string,
  persona: PersonaKey | null,
  annotation: CardAnnotation,
  shift: -1 | 1,
): Promise<Explanation> {
  const key = keyOf(persona, contentId, annotation.id, shift);
  const hit = cache.get(key);
  if (hit) return hit;
  const pending = api.explain(contentId, { demand_id: annotation.id, shift }, persona).then(toExplanation);
  cache.set(key, pending);
  pending.catch(() => cache.delete(key));
  return pending;
}

/** Warm the cache for the highest-scoring spans. */
export function prefetchExplanations(
  contentId: string,
  persona: PersonaKey | null,
  annotations: readonly CardAnnotation[],
): void {
  const top = [...annotations]
    .filter((a) => a.kind === "span")
    .sort((a, b) => b.score - a.score)
    .slice(0, PREFETCH_TOP);
  for (const a of top) loadExplanation(contentId, persona, a, true).catch(() => undefined);
}

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
  already: Iterable<string> = [],
): Prefetcher {
  const seen = new Set(already);
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
): () => void {
  if (persona !== null || typeof IntersectionObserver === "undefined") return () => undefined;
  const byId = new Map(annotations.filter((a) => a.kind === "span").map((a) => [a.id, a]));
  const top = [...annotations]
    .filter((a) => a.kind === "span")
    .sort((a, b) => b.score - a.score)
    .slice(0, PREFETCH_TOP)
    .map((a) => a.id);
  const queue = makePrefetcher(
    (id) => loadExplanation(contentId, persona, byId.get(id)!, true),
    PREFETCH_MAX,
    PREFETCH_IN_FLIGHT,
    top,
  );
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

/** "This is wrong": evict server-side, record report_wrong, and drop our copy. */
export async function reportExplanation(
  contentId: string,
  persona: PersonaKey | null,
  annotationId: string,
  explanationId: string,
  conceptId: string | null,
): Promise<void> {
  for (const shift of [0, -1, 1]) cache.delete(keyOf(persona, contentId, annotationId, shift));
  await api.reportExplanation(
    explanationId,
    { event_id: crypto.randomUUID(), content_id: contentId, concept_id: conceptId },
    persona,
  );
}
