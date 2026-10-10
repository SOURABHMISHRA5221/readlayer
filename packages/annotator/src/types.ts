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
  /** The reader's frame the Background drew an analogy from, if any. */
  analogy_domain?: string | null;
}

/** "What this paragraph is saying" margin marker (DESIGN §6, §9). */
export interface ParagraphMarker {
  id: string;
  kind: "paragraph";
  paragraph_id: string;
  score: number;
  domain?: string | null;
}

/** The "Know this?" uncertainty prompt, shown inline after its term. */
export interface PromptAnnotation {
  id: string;
  kind: "prompt";
  anchor: Anchor;
  paragraph_id: string;
  concept_id: string;
  label: string;
}

export interface PrereadStep {
  concept_id: string;
  label: string;
  definition: string;
  /** A library article that explains the concept; else the step shows its definition. */
  content_id?: string | null;
  title?: string | null;
}

/** Pre-read card: what to meet before this article, most basic first. */
export interface PrereadAnnotation {
  id: string;
  kind: "preread";
  score: number;
  concept_id: string;
  label: string;
  steps: PrereadStep[];
}

/** Everything the annotations endpoint returns; the annotator draws all but the pre-read. */
export type AnyAnnotation = CardAnnotation | ParagraphMarker | PromptAnnotation | PrereadAnnotation;

export type AnnotatorEventType =
  | "explain_opened"
  | "knew_this"
  | "explain_helpful"
  | "report_wrong"
  | "annotation_dismissed"
  | "text_searched"
  | "paragraph_dwell";

export interface AnnotatorEvent {
  type: AnnotatorEventType;
  /** The span or paragraph marker acted on; null for reading signals (dwell, search). */
  annotation_id: string | null;
  concept_id: string | null;
  at: string;
  /** report_wrong only: the explanation being reported. */
  explanation_id?: string;
  paragraph_id?: string;
  /** paragraph_dwell: the paragraph's words on its first dwell in a page view, 0 after. */
  words?: number;
  ms?: number;
}
