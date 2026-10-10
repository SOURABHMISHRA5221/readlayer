/**
 * "What this paragraph is saying" margin markers (DESIGN §9). A marker is a button placed at the
 * start of its paragraph and drawn in the margin; it opens the shared card in paragraph mode.
 */

import type { CardAnnotation, ParagraphMarker } from "./types";
import { UI_ATTR } from "./ui";

export const PARAGRAPH_TITLE = "What this paragraph is saying";
export const PMARK_CLASS = "rl-pmark";

export function createMarker(doc: Document, marker: ParagraphMarker, cardId: string): HTMLButtonElement {
  const b = doc.createElement("button");
  b.type = "button";
  b.className = PMARK_CLASS;
  b.setAttribute(UI_ATTR, "");
  b.dataset.rlMarker = marker.id;
  b.setAttribute("aria-label", PARAGRAPH_TITLE);
  b.setAttribute("aria-haspopup", "dialog");
  b.setAttribute("aria-expanded", "false");
  b.setAttribute("aria-controls", cardId);
  b.title = PARAGRAPH_TITLE;
  const glyph = doc.createElement("span");
  glyph.className = `${PMARK_CLASS}__glyph`;
  glyph.setAttribute("aria-hidden", "true");
  b.append(glyph);
  return b;
}

/** What the shared card shows for a paragraph before (and without) its explanation. */
export function paragraphCard(marker: ParagraphMarker): CardAnnotation {
  return {
    id: marker.id,
    kind: "paragraph",
    anchor: { exact: "", prefix: "", suffix: "" },
    paragraph_id: marker.paragraph_id,
    score: marker.score,
    concept_id: null,
    label: PARAGRAPH_TITLE,
    definition: "",
    domain: marker.domain ?? undefined,
    prerequisites: [],
  };
}
