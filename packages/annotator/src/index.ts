/**
 * Shared annotation overlay used by the web app and the extension (DESIGN §9).
 * M0 ships only the anchor contract; rendering and events arrive in M6.
 */

/** W3C TextQuoteSelector plus char offsets as a resolution hint. */
export interface Anchor {
  exact: string;
  prefix: string;
  suffix: string;
  start?: number;
  end?: number;
}

export type AnnotationKind = "span" | "paragraph" | "preread" | "prompt";

export interface Annotation {
  id: string;
  kind: AnnotationKind;
  anchor: Anchor;
  paragraph_id: string;
  score: number;
  concept_id: string | null;
  label: string;
}

export const ANNOTATOR_VERSION = "0.1.0";
