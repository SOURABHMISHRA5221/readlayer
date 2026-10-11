import type { CardAnnotation, Explanation } from "@readlayer/annotator";

import type { PersonaKey } from "../lib/personas";
import { personas } from "./demo.json";

/**
 * The landing demo's data (plan A4): verified, cached notes for one real paragraph, written by
 * apps/api/scripts/build_landing_demo.py. Everything the landing shows about the personas is
 * derived from it, never written by hand.
 */
type DemoAnnotation = CardAnnotation & { explanation: Explanation };

interface DemoPersona {
  label: string;
  frame: string;
  annotations: DemoAnnotation[];
}

const DATA = personas as unknown as Record<PersonaKey, DemoPersona>;

/** The span annotations the persona's reader sees, as the annotator takes them. */
export function demoAnnotations(persona: PersonaKey): CardAnnotation[] {
  return DATA[persona].annotations.map(({ explanation: _explanation, ...annotation }) => annotation);
}

/** The persona's verified explanation for one span, or null if the data has none. */
export function demoExplanation(persona: PersonaKey, annotationId: string): Explanation | null {
  return DATA[persona].annotations.find((a) => a.id === annotationId)?.explanation ?? null;
}

export interface DemoNote {
  term: string;
  label: string;
  level: "new" | "refresher";
  /** The Background's analogy sentence, verbatim, when the note drew on the reader's frame. */
  analogy: string | null;
  analogyDomain: string | null;
}

/** One sentence of the Background that carries the analogy ("… like …"), quoted as written. */
export function analogySentence(background: string | null): string | null {
  if (!background) return null;
  const sentences = background.match(/[^.!?]+[.!?]+/g) ?? [];
  return sentences.map((s) => s.trim()).find((s) => /\blike\b/i.test(s)) ?? null;
}

/** The persona's notes in paragraph order, for the static side-by-side. */
export function demoNotes(persona: PersonaKey): DemoNote[] {
  return [...DATA[persona].annotations]
    .sort((a, b) => (a.anchor.start ?? 0) - (b.anchor.start ?? 0))
    .map((a) => ({
      term: a.anchor.exact,
      label: a.label,
      level: a.level ?? "new",
      analogy: a.explanation.analogy_domain ? analogySentence(a.explanation.background) : null,
      analogyDomain: a.explanation.analogy_domain ?? null,
    }));
}

/** "2 new ideas" / "1 new idea and 1 refresher": the side-by-side's caption, from the data. */
export function noteCount(notes: DemoNote[]): string {
  const fresh = notes.filter((n) => n.level === "new").length;
  const refreshers = notes.length - fresh;
  const part = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
  const parts = [fresh ? part(fresh, "new idea", "new ideas") : null, refreshers ? part(refreshers, "refresher", "refreshers") : null];
  return parts.filter(Boolean).join(" and ") || "no notes";
}

/** One persona's note as the static first paint shows it (decision 46): the span and its verified explanation. */
export function demoNote(persona: PersonaKey, annotationId: string): DemoAnnotation | null {
  return DATA[persona].annotations.find((a) => a.id === annotationId) ?? null;
}
