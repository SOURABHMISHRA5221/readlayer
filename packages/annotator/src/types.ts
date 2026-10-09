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

/** What a span card shows before its explanation loads (and when there is none). */
export interface CardAnnotation extends Annotation {
  definition: string;
  /** Graph domain, shown as the card's small-caps label. */
  domain?: string;
  prerequisites: string[];
  debug?: AnnotationDebug | null;
}

/**
 * A verified two-part explanation (DESIGN §7), or `definition` when none passed the verifier
 * (the card then keeps showing the definition only).
 */
export interface Explanation {
  /** Cache entry id; "This is wrong" names it. */
  id: string;
  kind: "verified" | "definition";
  background: string | null;
  author_says: string | null;
}

export type AnnotatorEventType =
  | "explain_opened"
  | "knew_this"
  | "explain_helpful"
  | "report_wrong";

export interface AnnotatorEvent {
  type: AnnotatorEventType;
  annotation_id: string;
  concept_id: string | null;
  at: string;
  /** report_wrong only: the explanation being reported. */
  explanation_id?: string;
}
