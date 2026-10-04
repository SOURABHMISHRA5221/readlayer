import {
  createAnnotator,
  type Annotator,
  type AnnotatorEvent,
  type CardAnnotation,
} from "@readlayer/annotator";
import { useCallback, useEffect, useRef, useState, type RefObject } from "react";

import { trackEvent } from "../lib/events";
import type { PersonaKey } from "../lib/personas";

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
    const onEvent = (event: AnnotatorEvent) =>
      trackEvent(event.type, event.concept_id, articleKey, personaRef.current);
    const annotator = createAnnotator(el, {
      onEvent,
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
    annotator.update(annotations).then((result) => {
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
