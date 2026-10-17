import type { CardAnnotation, ParagraphMarker, SelectionAsk } from "@readlayer/annotator";

/** What "Explain" on a selection does (decision 70): open a note, adding it first if needed. */
export type AskPlan = { open: string; add?: CardAnnotation | ParagraphMarker };

interface PageNotes {
  spans: readonly CardAnnotation[];
  markers: readonly ParagraphMarker[];
}

/**
 * The selected term's card (the mark already on the page for its concept, else the term added);
 * with no term, or when the lookup fails, the paragraph's card.
 */
export async function planAsk(
  ask: SelectionAsk,
  page: PageNotes,
  lookup: (ask: SelectionAsk) => Promise<CardAnnotation | null>,
): Promise<AskPlan> {
  let hit: CardAnnotation | null = null;
  try {
    hit = await lookup(ask);
  } catch {
    hit = null; // offline or refused: the paragraph's card still answers the question
  }
  if (!hit) return paragraphFallback(ask.paragraph_id, page.markers);
  const shown = page.spans.find((s) => s.id === hit.id || (hit.concept_id !== null && s.concept_id === hit.concept_id));
  return shown ? { open: shown.id } : { add: hit, open: hit.id };
}

/** The paragraph's "What this paragraph is saying" card, its ¶ marker added when absent. */
export function paragraphFallback(paragraphId: string, markers: readonly ParagraphMarker[]): AskPlan {
  const id = `para:${paragraphId}`;
  if (markers.some((m) => m.id === id)) return { open: id };
  return { add: { id, kind: "paragraph", paragraph_id: paragraphId, score: 0 }, open: id };
}

/** After an update: open the asked note once placed; fall back when it couldn't be (decision 70). */
export function afterPlaced(
  pendingId: string,
  result: { resolved: readonly string[]; paragraphs: readonly string[]; unresolved: readonly string[] },
): "open" | "fallback" | "wait" {
  if (result.resolved.includes(pendingId) || result.paragraphs.includes(pendingId)) return "open";
  return result.unresolved.includes(pendingId) ? "fallback" : "wait";
}
