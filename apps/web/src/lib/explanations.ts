import type { CardAnnotation, Explanation, FrameChoice } from "@readlayer/annotator";

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

const keyOf = (
  persona: PersonaKey | null,
  contentId: string,
  annotationId: string,
  shift = 0,
  frame: FrameChoice = "pick",
) => `${persona ?? "me"}|${contentId}|${annotationId}|${shift}|${frame}`;

const toExplanation = (r: Awaited<ReturnType<typeof api.explain>>): Explanation => ({
  id: r.id,
  kind: r.kind,
  background: r.background,
  author_says: r.author_says,
  analogy_domain: r.analogy_domain,
  band: r.band,
  can_simpler: r.can_simpler,
  can_deeper: r.can_deeper,
  frames: r.frames,
});

export function loadExplanation(
  contentId: string,
  persona: PersonaKey | null,
  annotation: CardAnnotation,
  prefetch = false,
  frame: FrameChoice = "pick",
): Promise<Explanation> {
  const key = keyOf(persona, contentId, annotation.id, 0, frame);
  const hit = cache.get(key);
  if (hit) return hit;
  // Paragraph markers are explained by paragraph; spans by their demand id.
  const which = frame === "for_you" ? { frame: "for_you" as const } : {};
  const target =
    annotation.kind === "paragraph"
      ? { paragraph_id: annotation.paragraph_id, ...which }
      : { demand_id: annotation.id, ...which };
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

/**
 * The Background in the other analogy frame (decision 67 A4): only on click, never prefetched
 * except in the frame the reader chose for the page. "pick" goes through the usual loaders.
 */
export function loadFramed(
  contentId: string,
  persona: PersonaKey | null,
  annotation: CardAnnotation,
  frame: FrameChoice,
  shift: -1 | 0 | 1,
): Promise<Explanation> {
  if (frame === "pick") {
    return shift ? loadShifted(contentId, persona, annotation, shift) : loadExplanation(contentId, persona, annotation);
  }
  if (!shift) return loadExplanation(contentId, persona, annotation, false, "for_you");
  const key = keyOf(persona, contentId, annotation.id, shift, "for_you");
  const hit = cache.get(key);
  if (hit) return hit;
  const pending = api
    .explain(contentId, { demand_id: annotation.id, shift, frame: "for_you" }, persona)
    .then(toExplanation);
  cache.set(key, pending);
  pending.catch(() => cache.delete(key));
  return pending;
}

/** Warm the cache for the highest-scoring spans, in the page's frame. */
export function prefetchExplanations(
  contentId: string,
  persona: PersonaKey | null,
  annotations: readonly CardAnnotation[],
  frame: FrameChoice = "pick",
): void {
  const top = [...annotations]
    .filter((a) => a.kind === "span")
    .sort((a, b) => b.score - a.score)
    .slice(0, PREFETCH_TOP);
  for (const a of top) loadExplanation(contentId, persona, a, true, frame).catch(() => undefined);
}

/** "This is wrong": evict server-side, record report_wrong, and drop our copy. */
export async function reportExplanation(
  contentId: string,
  persona: PersonaKey | null,
  annotationId: string,
  explanationId: string,
  conceptId: string | null,
): Promise<void> {
  for (const shift of [0, -1, 1]) {
    for (const frame of ["pick", "for_you"] as const) cache.delete(keyOf(persona, contentId, annotationId, shift, frame));
  }
  await api.reportExplanation(
    explanationId,
    { event_id: crypto.randomUUID(), content_id: contentId, concept_id: conceptId },
    persona,
  );
}
