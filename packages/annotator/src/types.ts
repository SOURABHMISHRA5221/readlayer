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

/** Scoring internals, present only when the API runs in dev with `debug=1`. */
export interface AnnotationDebug {
  p_know: number;
  salience: number;
  span_score: number;
  domain: string;
  base_difficulty: number;
}

/** What a span card shows. Explanations (DESIGN §7) will add fields here in M5. */
export interface CardAnnotation extends Annotation {
  definition: string;
  prerequisites: string[];
  debug?: AnnotationDebug | null;
}

export type AnnotatorEventType = "explain_opened" | "knew_this" | "explain_helpful";

export interface AnnotatorEvent {
  type: AnnotatorEventType;
  annotation_id: string;
  concept_id: string | null;
  at: string;
}
