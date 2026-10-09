import {
  createAnnotator,
  type Annotator,
  type AnnotatorEvent,
  type CardAnnotation,
  type SidenoteBox,
} from "@readlayer/annotator";
import { useCallback, useEffect, useRef, useState, type RefObject } from "react";

import { trackEvent } from "../lib/events";
import { loadExplanation, prefetchExplanations, reportExplanation } from "../lib/explanations";
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
}

/**
 * One annotator per rendered article (keyed by `articleKey`). Annotation changes go through
 * update(), so a persona or density switch animates only the notes that differ.
 */
export function useAnnotator(
  root: RefObject<HTMLElement | null>,
  articleKey: string | null,
  annotations: CardAnnotation[] | null,
  persona: PersonaKey | null,
): AnnotatorHandle {
  const annotatorRef = useRef<Annotator | null>(null);
  // Read at event time, so a persona switch doesn't rebuild the annotator.
  const personaRef = useRef(persona);
  personaRef.current = persona;
  const [resolved, setResolved] = useState<string[] | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const [active, setActive] = useState<string | null>(null);

  useEffect(() => {
    const el = root.current;
    if (!el || !articleKey) return;
    const onEvent = (event: AnnotatorEvent) => {
      // A report evicts the shared entry and records report_wrong in one server call.
      if (event.type === "report_wrong") {
        if (event.explanation_id) {
          void reportExplanation(
            articleKey, personaRef.current, event.annotation_id, event.explanation_id, event.concept_id,
          ).catch(() => undefined);
        }
        return;
      }
      trackEvent(event.type, event.concept_id, articleKey, personaRef.current);
    };
    const annotator = createAnnotator(el, {
      onEvent,
      loadExplanation: (a) => loadExplanation(articleKey, personaRef.current, a),
      sidenote: () => railColumn(el),
      onHover: setHovered,
      onActive: setActive,
    });
    annotatorRef.current = annotator;
    return () => {
      annotator.destroy();
      annotatorRef.current = null;
      setResolved(null);
      setHovered(null);
      setActive(null);
    };
  }, [root, articleKey]);

  useEffect(() => {
    const annotator = annotatorRef.current;
    if (!annotator || !annotations) return;
    let cancelled = false;
    if (articleKey) prefetchExplanations(articleKey, personaRef.current, annotations);
    // The persona is the reader: switching it reloads an open card and resets its actions.
    annotator.update(annotations, { reader: personaRef.current ?? "me" }).then((result) => {
      if (cancelled) return;
      setResolved(result.resolved);
      if (result.unresolved.length) console.warn("[readlayer] anchors not found", result.unresolved);
    });
    return () => {
      cancelled = true;
    };
  }, [annotations, articleKey]);

  const highlight = useCallback((id: string | null) => annotatorRef.current?.highlight(id), []);
  const open = useCallback((id: string, focus = false) => annotatorRef.current?.open(id, { focus }), []);

  return { resolved, hovered, active, highlight, open };
}
