import {
  createAnnotator,
  type Annotator,
  type AnnotatorEvent,
  type CardAnnotation,
  type ParagraphMarker,
  type PromptAnnotation,
  type SidenoteBox,
} from "@readlayer/annotator";
import { useCallback, useEffect, useRef, useState, type RefObject } from "react";

import { answerAndRefresh } from "../lib/answers";
import { api } from "../lib/api";
import { onBeforeFlush, trackEvent } from "../lib/events";
import { loadExplanation, loadShifted, prefetchExplanations, reportExplanation } from "../lib/explanations";
import type { PersonaKey } from "../lib/personas";

const WIDE_PX = 1200; // the margin rail appears here (reader.css)
const SIDENOTE_MAX_PX = 360;
const EDGE_PX = 16;

/** The margin rail's column, when it is on screen: cards become sidenotes there. */
function railColumn(root: HTMLElement): SidenoteBox | null {
  const view = root.ownerDocument.defaultView;
  if (!view || view.innerWidth < WIDE_PX) return null;
  const rail = root.closest(".reader__body")?.querySelector<HTMLElement>(".rail");
  const box = rail?.getBoundingClientRect();
  if (!box || box.width === 0) return null;
  return { left: box.left, width: Math.min(SIDENOTE_MAX_PX, view.innerWidth - box.left - EDGE_PX) };
}

export interface AnnotatorHandle {
  /** Ids of annotations currently marked, in document order; null until the first update. */
  resolved: string[] | null;
  hovered: string | null;
  active: string | null;
  highlight: (id: string | null) => void;
  open: (id: string, focus?: boolean) => void;
  /** "Know this?" answers this page view: concept id → { label, known } (for the recap). */
  answers: ReadonlyMap<string, { label: string; known: boolean }>;
}

/**
 * One annotator per rendered article (keyed by `articleKey`). Annotation changes go through
 * update(), so a persona or density switch animates only the notes that differ. `extras` are
 * the paragraph markers and the "Know this?" prompt.
 */
export function useAnnotator(
  root: RefObject<HTMLElement | null>,
  articleKey: string | null,
  annotations: CardAnnotation[] | null,
  extras: (ParagraphMarker | PromptAnnotation)[] | null,
  persona: PersonaKey | null,
  /** Refetch the article's annotations after a saved "Know this?" answer (decision 46d). */
  refreshNotes?: () => Promise<void>,
): AnnotatorHandle {
  const annotatorRef = useRef<Annotator | null>(null);
  // Read at event time, so a persona switch doesn't rebuild the annotator.
  const personaRef = useRef(persona);
  personaRef.current = persona;
  const refreshRef = useRef(refreshNotes);
  refreshRef.current = refreshNotes;
  const [resolved, setResolved] = useState<string[] | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const [active, setActive] = useState<string | null>(null);
  const [answers, setAnswers] = useState<ReadonlyMap<string, { label: string; known: boolean }>>(new Map());

  useEffect(() => {
    const el = root.current;
    if (!el || !articleKey) return;
    const onEvent = (event: AnnotatorEvent) => {
      // A report evicts the shared entry and records report_wrong in one server call.
      if (event.type === "report_wrong") {
        if (event.explanation_id && event.annotation_id) {
          void reportExplanation(
            articleKey, personaRef.current, event.annotation_id, event.explanation_id, event.concept_id,
          ).catch(() => undefined);
        }
        return;
      }
      trackEvent(event.type, event.concept_id, articleKey, personaRef.current, {
        ...(event.paragraph_id ? { paragraph_id: event.paragraph_id } : {}),
        ...(event.words !== undefined ? { words: event.words } : {}),
        ...(event.ms !== undefined ? { ms: event.ms } : {}),
      });
    };
    const annotator = createAnnotator(el, {
      onEvent,
      // "Know this?": the reader's own word goes straight to their graph (DESIGN §6.5).
      onAnswer: (prompt, known) =>
        answerAndRefresh({
          save: async () => {
            await api.correct(prompt.concept_id, known, personaRef.current);
            setAnswers((m) => new Map(m).set(prompt.concept_id, { label: prompt.label, known }));
          },
          refresh: () => refreshRef.current?.() ?? Promise.resolve(),
        }),
      loadExplanation: (a) => loadExplanation(articleKey, personaRef.current, a),
      loadShifted: (a, shift) => loadShifted(articleKey, personaRef.current, a, shift),
      sidenote: () => railColumn(el),
      onHover: setHovered,
      onActive: setActive,
    });
    annotatorRef.current = annotator;
    const unhook = onBeforeFlush(() => annotator.flush());
    return () => {
      unhook();
      annotator.destroy();
      annotatorRef.current = null;
      setResolved(null);
      setHovered(null);
      setActive(null);
      setAnswers(new Map());
    };
  }, [root, articleKey]);

  useEffect(() => {
    const annotator = annotatorRef.current;
    if (!annotator || !annotations) return;
    let cancelled = false;
    if (articleKey) prefetchExplanations(articleKey, personaRef.current, annotations);
    // The persona is the reader: switching it reloads an open card and resets its actions.
    annotator.update([...annotations, ...(extras ?? [])], { reader: personaRef.current ?? "me" }).then((result) => {
      if (cancelled) return;
      setResolved(result.resolved);
      if (result.unresolved.length) console.warn("[readlayer] anchors not found", result.unresolved);
    });
    return () => {
      cancelled = true;
    };
  }, [annotations, extras, articleKey]);

  const highlight = useCallback((id: string | null) => annotatorRef.current?.highlight(id), []);
  const open = useCallback((id: string, focus = false) => annotatorRef.current?.open(id, { focus }), []);

  return { resolved, hovered, active, highlight, open, answers };
}
