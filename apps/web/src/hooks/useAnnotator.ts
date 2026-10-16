import {
  createAnnotator,
  type Annotator,
  type AnnotatorEvent,
  type CardLabels,
  type CardAnnotation,
  type FrameChoice,
  type NextUpChip,
  type ParagraphMarker,
  type PromptAnnotation,
  type SidenoteBox,
} from "@readlayer/annotator";
import { useCallback, useEffect, useRef, useState, type RefObject } from "react";

import { answerAndRefresh } from "../lib/answers";
import { api, type RecItem } from "../lib/api";
import { onBeforeFlush, trackEvent } from "../lib/events";
import {
  loadExplanation,
  loadFramed,
  loadShifted,
  prefetchExplanations,
  reportExplanation,
} from "../lib/explanations";
import { loadNextUp, shownOnce, toChips } from "../lib/nextUp";
import { openRec } from "../lib/openRec";
import { queueRecEvent } from "../lib/recEvents";
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
  // Up to the content's right edge, not the window's: a classic scrollbar is inside innerWidth.
  const right = root.ownerDocument.documentElement.clientWidth || view.innerWidth;
  return { left: box.left, width: Math.min(SIDENOTE_MAX_PX, right - box.left - EDGE_PX) };
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
  /** Card wording for a transcript ("What the speaker is saying"); keep the value stable. */
  labels?: CardLabels,
): AnnotatorHandle {
  const annotatorRef = useRef<Annotator | null>(null);
  // Read at event time, so a persona switch doesn't rebuild the annotator.
  const personaRef = useRef(persona);
  personaRef.current = persona;
  const refreshRef = useRef(refreshNotes);
  refreshRef.current = refreshNotes;
  // Decision 67 L3: notes prefetched on this article, across notes refreshes.
  const prefetchedRef = useRef<{ key: string | null; ids: Set<string> }>({ key: null, ids: new Set() });
  // Decision 67 N3: the card's Up next chips (article-basis items), per page.
  const recItemsRef = useRef<RecItem[]>([]);
  const chipsRef = useRef<NextUpChip[]>([]);
  const shownRef = useRef<Set<string>>(new Set());
  // Decision 67 A4: the analogy frame chosen on this page (the annotator remembers it too).
  const frameRef = useRef<FrameChoice>("pick");
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
      onAnswer: (prompt, known) => {
        // The refresh for this view: ReaderPage's callback changes with article, persona or density.
        const refresh = refreshRef.current;
        return answerAndRefresh({
          save: async () => {
            await api.correct(prompt.concept_id, known, personaRef.current);
            setAnswers((m) => new Map(m).set(prompt.concept_id, { label: prompt.label, known }));
          },
          refresh: () => refresh?.() ?? Promise.resolve(),
          // Still the same view as when answered (annotator mounted, same refresh callback).
          isCurrent: () => annotatorRef.current === annotator && refreshRef.current === refresh,
        });
      },
      loadExplanation: (a) => loadExplanation(articleKey, personaRef.current, a),
      loadShifted: (a, shift) => loadShifted(articleKey, personaRef.current, a, shift),
      loadFramed: (a, frame, shift) => loadFramed(articleKey, personaRef.current, a, frame, shift),
      onFrameChoice: (frame) => {
        frameRef.current = frame;
      },
      sidenote: () => railColumn(el),
      nextUp: () => chipsRef.current,
      onNextUp: (chip) => {
        const item = recItemsRef.current.find((i) => i.id === chip.id);
        if (!item) return;
        queueRecEvent(personaRef.current, "rec_clicked", item.id);
        void openRec(item, personaRef.current, articleKey);
      },
      onNextUpShown: (ids) => {
        for (const id of shownOnce(shownRef.current, ids)) queueRecEvent(personaRef.current, "rec_shown", id);
      },
      labels,
      onHover: setHovered,
      onActive: setActive,
    });
    annotatorRef.current = annotator;
    frameRef.current = "pick"; // a new annotator starts in the reader's own pick
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
  }, [root, articleKey, labels]);

  useEffect(() => {
    const annotator = annotatorRef.current;
    if (!annotator || !annotations) return;
    let cancelled = false;
    if (articleKey) prefetchExplanations(articleKey, personaRef.current, annotations, frameRef.current);
    // The persona is the reader: switching it reloads an open card and resets its actions.
    let stopPrefetch = () => {};
    annotator.update([...annotations, ...(extras ?? [])], { reader: personaRef.current ?? "me" }).then((result) => {
      if (cancelled) return;
      setResolved(result.resolved);
      if (result.unresolved.length) console.warn("[readlayer] anchors not found", result.unresolved);
      // Marks exist now: notes near the viewport warm up (signed-in only, decision 67 L3).
      const el = root.current;
      if (!articleKey || !el || personaRef.current !== null) return;
      if (prefetchedRef.current.key !== articleKey) prefetchedRef.current = { key: articleKey, ids: new Set() };
      const seen = prefetchedRef.current.ids;
      import("../lib/prefetchInView")
        .then(({ prefetchInView }) => {
          if (cancelled) return;
          stopPrefetch = prefetchInView(el, articleKey, personaRef.current, annotations, seen, () => frameRef.current);
        })
        .catch(() => undefined); // a stale chunk after a deploy: no prefetch, nothing breaks
    });
    return () => {
      cancelled = true;
      stopPrefetch();
    };
  }, [annotations, extras, articleKey]);

  useEffect(() => {
    recItemsRef.current = [];
    chipsRef.current = [];
    shownRef.current = new Set();
    if (!articleKey) return;
    return loadNextUp(articleKey, persona, (items) => {
      recItemsRef.current = items;
      chipsRef.current = toChips(items, persona, articleKey);
    });
  }, [articleKey, persona]);

  const highlight = useCallback((id: string | null) => annotatorRef.current?.highlight(id), []);
  const open = useCallback((id: string, focus = false) => annotatorRef.current?.open(id, { focus }), []);

  return { resolved, hovered, active, highlight, open, answers };
}
