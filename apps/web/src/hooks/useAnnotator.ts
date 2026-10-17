import {
  createAnnotator,
  type Annotator,
  type AnnotatorEvent,
  type CardLabels,
  type CardAnnotation,
  type FrameChoice,
  type ParagraphMarker,
  type PromptAnnotation,
  type SelectionAsk,
  type SidenoteBox,
} from "@readlayer/annotator";
import { useCallback, useEffect, useRef, useState, type RefObject } from "react";

import { answerAndRefresh } from "../lib/answers";
import { api } from "../lib/api";
import { onBeforeFlush, trackEvent } from "../lib/events";
import {
  loadExplanation,
  loadFramed,
  loadShifted,
  prefetchExplanations,
  reportExplanation,
} from "../lib/explanations";
import { shownOnce } from "../lib/nextUp";
import { paragraphFallback, planAsk, type AskPlan } from "../lib/selectionLookup";
import { openRec } from "../lib/openRec";
import { queueRecEvent } from "../lib/recEvents";
import { useNextUp } from "./useNextUp";
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
  /** Placed ¶ paragraph marker ids, in document order (decision 70); null until the first update. */
  paragraphs: string[] | null;
  hovered: string | null;
  active: string | null;
  highlight: (id: string | null) => void;
  open: (id: string, focus?: boolean) => void;
  /** "Know this?" answers this page view: concept id → { label, known } (for the recap). */
  answers: ReadonlyMap<string, { label: string; known: boolean }>;
  /** Notes the reader added by selecting text this view (decision 70): words and ¶ markers. */
  asked: { spans: CardAnnotation[]; markers: ParagraphMarker[] };
}

const NO_ASKED: AnnotatorHandle["asked"] = { spans: [], markers: [] };

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
  // Decision 67 N3: the card's Up next chips, asked once this page's notes are in (decision 68 B).
  const nextUp = useNextUp(articleKey, persona, annotations !== null, () => annotatorRef.current?.refreshNextUp());
  // Decision 67 A4: the analogy frame chosen on this page (the annotator remembers it too).
  const frameRef = useRef<FrameChoice>("pick");
  const [resolved, setResolved] = useState<string[] | null>(null);
  const [paragraphs, setParagraphs] = useState<string[] | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const [active, setActive] = useState<string | null>(null);
  const [answers, setAnswers] = useState<ReadonlyMap<string, { label: string; known: boolean }>>(new Map());
  // Decision 70: notes added by "Explain" on a selection, for this article and reader only.
  const [asked, setAsked] = useState<{ key: string; notes: AnnotatorHandle["asked"] }>({ key: "", notes: NO_ASKED });
  const askedKey = `${articleKey ?? ""}|${persona ?? ""}`;
  const notesNow = asked.key === askedKey ? asked.notes : NO_ASKED;
  const pageRef = useRef({ spans: [] as CardAnnotation[], markers: [] as ParagraphMarker[] });
  pageRef.current = {
    spans: [...(annotations ?? []), ...notesNow.spans],
    markers: [...(extras ?? []).filter((x): x is ParagraphMarker => x.kind === "paragraph"), ...notesNow.markers],
  };
  const pendingOpen = useRef<{ id: string; paragraphId: string } | null>(null);
  const applyPlan = useCallback(
    (plan: AskPlan, paragraphId: string) => {
      const add = plan.add;
      if (!add) {
        annotatorRef.current?.open(plan.open, { focus: true });
        return;
      }
      pendingOpen.current = { id: plan.open, paragraphId };
      setAsked((prev) => {
        const base = prev.key === askedKey ? prev.notes : NO_ASKED;
        const notes = add.kind === "paragraph"
          ? { ...base, markers: [...base.markers, add as ParagraphMarker] }
          : { ...base, spans: [...base.spans, add as CardAnnotation] };
        return { key: askedKey, notes };
      });
    },
    [askedKey],
  );
  const applyRef = useRef(applyPlan);
  applyRef.current = applyPlan;
  const askRef = useRef<(ask: SelectionAsk) => void>(() => undefined);
  askRef.current = (ask) => {
    if (!articleKey) return;
    void planAsk(ask, pageRef.current, (a) => api.lookup(articleKey, a, personaRef.current)).then((plan) =>
      applyPlan(plan, ask.paragraph_id),
    );
  };

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
      nextUp: () => nextUp.chips.current,
      onNextUp: (chip) => {
        const item = nextUp.items.current.find((i) => i.id === chip.id);
        if (!item) return;
        queueRecEvent(personaRef.current, "rec_clicked", item.id);
        void openRec(item, personaRef.current, articleKey);
      },
      onNextUpShown: (ids) => {
        for (const id of shownOnce(nextUp.shown.current, ids)) queueRecEvent(personaRef.current, "rec_shown", id);
      },
      labels,
      onSelectionExplain: (ask) => askRef.current(ask),
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
      setParagraphs(null);
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
    const ids = new Set(annotations.map((a) => a.id));
    const extraIds = new Set((extras ?? []).map((a) => a.id));
    const all = [
      ...annotations,
      ...notesNow.spans.filter((a) => !ids.has(a.id)),
      ...(extras ?? []),
      ...notesNow.markers.filter((m) => !extraIds.has(m.id)),
    ];
    annotator.update(all, { reader: personaRef.current ?? "me" }).then((result) => {
      if (cancelled) return;
      setResolved(result.resolved);
      setParagraphs(result.paragraphs);
      const pending = pendingOpen.current;
      if (pending) {
        if (result.resolved.includes(pending.id) || result.paragraphs.includes(pending.id)) {
          pendingOpen.current = null;
          annotator.open(pending.id, { focus: true });
        } else if (result.unresolved.includes(pending.id)) {
          // It overlaps another mark: drop it and answer with the paragraph's card.
          pendingOpen.current = null;
          setAsked((prev) => ({
            ...prev,
            notes: { ...prev.notes, spans: prev.notes.spans.filter((s) => s.id !== pending.id) },
          }));
          applyRef.current(paragraphFallback(pending.paragraphId, pageRef.current.markers), pending.paragraphId);
        }
      }
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
  }, [annotations, extras, articleKey, notesNow]);

  const highlight = useCallback((id: string | null) => annotatorRef.current?.highlight(id), []);
  const open = useCallback((id: string, focus = false) => annotatorRef.current?.open(id, { focus }), []);

  return { resolved, paragraphs, hovered, active, highlight, open, answers, asked: notesNow };
}
