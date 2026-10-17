import { paragraphCard, type CardAnnotation, type ParagraphMarker } from "@readlayer/annotator";

/**
 * Every note on the page in document order (decision 70): the marked words and the placed ¶
 * paragraph notes, so "N notes for you" counts what the reader can open. A ¶ note sits at its
 * paragraph's start, before that paragraph's words, and is named by its position ("Paragraph 3").
 */
export function pageNotes(
  spans: readonly CardAnnotation[],
  placedMarkerIds: readonly string[],
  markers: readonly ParagraphMarker[],
  articleParagraphs: readonly { id: string }[],
): CardAnnotation[] {
  const position = new Map(articleParagraphs.map((p, i) => [p.id, i]));
  const placed = new Set(placedMarkerIds);
  const paragraphNotes = markers
    .filter((m) => placed.has(m.id) && position.has(m.paragraph_id))
    .map((m) => ({ ...paragraphCard(m), label: `Paragraph ${position.get(m.paragraph_id)! + 1}` }));
  const ranked = [
    ...paragraphNotes.map((note) => ({ note, rank: 0 })),
    ...spans.map((note, i) => ({ note, rank: 1 + i })),
  ];
  const at = (n: CardAnnotation) => position.get(n.paragraph_id) ?? Number.MAX_SAFE_INTEGER;
  // Spans arrive in document order: sorting by paragraph then rank keeps it.
  return ranked.sort((a, b) => at(a.note) - at(b.note) || a.rank - b.rank).map((r) => r.note);
}
