/**
 * Shared annotation overlay used by the web app and the extension (DESIGN §9).
 * Framework-free: an Annotator wraps resolved spans in marks, drives one shared card, and
 * diffs updates so a persona or density change visibly swaps only the notes that differ.
 */

import { indexText, resolveInText, type TextRange } from "./anchor";
import { createAsk, type AnswerFn, type Ask } from "./ask";
import { Card, SHEET_QUERY, type CardLabels, type CardMode, type SidenoteBox } from "./card";
import { MARK_CLASS, markId, unwrap, wrapRange } from "./mark";
import { createMarker, paragraphCard, PMARK_CLASS } from "./paragraph";
import { Signals } from "./signals";
import { injectStyles, type StyleMode } from "./styles";
import type {
  AnnotatorEvent,
  AnnotatorEventType,
  AnyAnnotation,
  CardAnnotation,
  Anchor,
  Explanation,
  ParagraphMarker,
  PromptAnnotation,
} from "./types";
import { removeUi } from "./ui";
export { HOST_UI, UI_ATTR } from "./ui";

export type * from "./types";
export {
  AUTHOR_LABEL,
  BACKGROUND_LABEL,
  CARD_LABEL,
  NO_EXPLANATION_TEXT,
  type CardLabels,
  type SidenoteBox,
} from "./card";
export { normalizeWhitespace, resolveInText } from "./anchor";
export { MARK_CLASS, markId } from "./mark";
export { ASK_DONE, ASK_QUESTION, type AnswerFn } from "./ask";
export { PARAGRAPH_TITLE } from "./paragraph";
export { PREREAD_HEADING, renderPreread, type PrereadHandle, type PrereadOptions } from "./preread";

export { ANNOTATOR_CSS, type StyleMode } from "./styles";

export const ANNOTATOR_VERSION = "0.9.0";

export interface AnnotatorOptions {
  /** Interaction and reading events (DESIGN §9); the host batches them to /v1/events. */
  onEvent?: (event: AnnotatorEvent) => void;
  /**
   * A "Know this?" answer. The host records it (PATCH /v1/me/graph); a rejection lets the
   * reader try again.
   */
  onAnswer?: AnswerFn;
  /** A mark is hovered or focused (id), or no longer is (null). For linked UI like a rail. */
  onHover?: (id: string | null) => void;
  /** The card opened for an annotation (id) or closed (null). */
  onActive?: (id: string | null) => void;
  /**
   * Loads the verified explanation when a card opens (DESIGN §7): a span (`kind: "span"`) or a
   * paragraph marker (`kind: "paragraph"`, explained by `paragraph_id`). The card shows the
   * definition and a skeleton until it settles; a rejection keeps the definition only.
   * Hosts cache and prefetch inside this function, so a prefetched card fills at once.
   */
  loadExplanation?: (annotation: CardAnnotation) => Promise<Explanation>;
  /**
   * "Say it simpler" (-1) / "Go deeper" (+1): the explanation one band from the reader's own.
   * Optional: without it the card has no depth buttons (the extension's default).
   */
  loadShifted?: (annotation: CardAnnotation, shift: -1 | 1) => Promise<Explanation>;
  /**
   * Card actions. "full" (the default: reader and extension) shows Knew this / Helpful / This is
   * wrong; "demo" shows one call to action instead and records nothing (the landing page).
   */
  actions?: "full" | "demo";
  /** The demo card's call to action (with `actions: "demo"`). */
  demoAction?: { label: string; onClick: () => void };
  /** Card wording for content that isn't written by an author (a transcript's speaker). */
  labels?: CardLabels;
  /**
   * The page's margin column, when there is one (e.g. ≥1200px): the card is then set there as
   * a sidenote, level with its line, instead of floating over the text. Null = popover.
   */
  sidenote?: () => SidenoteBox | null;
  /**
   * An inline host (a landing demo): the card lives in this element, in flow, at every width.
   * One note stays open: no hover peeks, no closing on outside click, scroll or Escape, no focus
   * trap, and open() doesn't scroll. The card appears once its explanation has settled.
   */
  inline?: HTMLElement;
  /** The open card's explanation settled (shown, verified or not). */
  onCardReady?: (id: string) => void;
  /** "external": the host has applied ANNOTATOR_CSS itself (the extension); no <style>. */
  styles?: StyleMode;
  /** Attribute naming a paragraph element, used to scope anchor search. */
  paragraphAttribute?: string;
  hoverDelayMs?: number;
  closeDelayMs?: number;
  /** Fade-out time for removed marks; 0 under prefers-reduced-motion. */
  leaveMs?: number;
  /** Delay between successive entering marks. */
  staggerMs?: number;
}

export interface UpdateResult {
  /** Span annotation ids that are marked, in document order. */
  resolved: string[];
  /** Spans, prompts and markers that couldn't be placed (not found or overlapping). The
   * pre-read is the host's to render and never listed. */
  unresolved: string[];
}

export interface UpdateOptions {
  /**
   * Who is reading (e.g. a demo persona). When it changes, per-note actions (Knew this, This
   * is wrong) start fresh, and an open card reloads its explanation for the new reader.
   */
  reader?: string;
}

export interface Annotator {
  /** Spans, paragraph markers and the prompt; other kinds are ignored. */
  update(annotations: readonly AnyAnnotation[], options?: UpdateOptions): Promise<UpdateResult>;
  /** Emphasise one annotation's mark (e.g. while its rail chip is hovered); null clears. */
  highlight(id: string | null): void;
  /** Open an annotation's card, scrolling it into view; `focus` moves focus into the card. */
  open(id: string, options?: { focus?: boolean }): void;
  close(): void;
  /** Emit reading signals accumulated so far (call before sending a batch on page hide). */
  flush(): void;
  destroy(): void;
}

interface Entry {
  annotation: CardAnnotation;
  segments: HTMLElement[];
  start: number;
}

const ENTER_CLASS = `${MARK_CLASS}--entering`;
const LEAVE_CLASS = `${MARK_CLASS}--leaving`;
const LINK_CLASS = `${MARK_CLASS}--linked`;
const KNOWN_CLASS = `${MARK_CLASS}--known`;
const ASK_MARK_CLASS = `${MARK_CLASS}--ask`;
const HAS_MARKER_ATTR = "data-rl-has-marker";

interface Marker {
  item: ParagraphMarker;
  button: HTMLButtonElement;
}

interface Prompt {
  item: PromptAnnotation;
  segments: HTMLElement[];
  ask: Ask;
}

interface Active {
  id: string;
  /** Opened or pinned on purpose (click, tap, keyboard); hover peeks are not. */
  pinned: boolean;
  /** Knew this / Helpful / This is wrong pressed during this opening. */
  acted: boolean;
}

export function createAnnotator(root: HTMLElement, options: AnnotatorOptions = {}): Annotator {
  const doc = root.ownerDocument;
  const view = doc.defaultView;
  const attr = options.paragraphAttribute ?? "data-rl-paragraph";
  const hoverDelay = options.hoverDelayMs ?? 120;
  const closeDelay = options.closeDelayMs ?? 220;
  const reducedMotion = view?.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
  const leaveMs = reducedMotion ? 0 : (options.leaveMs ?? 180);
  const staggerMs = reducedMotion ? 0 : (options.staggerMs ?? 20);
  const emit = options.onEvent ?? (() => {});
  injectStyles(doc, options.styles);

  const entries = new Map<string, Entry>();
  const markers = new Map<string, Marker>();
  const prompts = new Map<string, Prompt>();
  // Prompts answered by this reader (a re-render after an update keeps them answered).
  const answered = new Set<string>();
  // Their chips, kept in their "Noted" state after the prompt left the list (cleared for a new reader).
  const released: HTMLElement[] = [];
  const pressed = new Map<string, Set<AnnotatorEventType>>();
  let active: Active | null = null;
  let linked: string | null = null;
  let hovered: string | null = null;
  let generation = 0;
  let openTimer: ReturnType<typeof setTimeout> | undefined;
  let closeTimer: ReturnType<typeof setTimeout> | undefined;
  let lastPointer = "mouse";
  // Latest explanation per open card; a response for a card no longer open is dropped.
  let loadToken = 0;
  const shown = new Map<string, Explanation>();
  let reader: string | undefined;
  // Sidenotes sit away from their mark, so a hover-opened one waits longer before closing.
  const SIDENOTE_CLOSE_MS = 700;

  const inline = options.inline ?? null;
  const card = new Card(doc, {
    onAction: (type) => {
      const target = active && lookup(active.id);
      if (!active || !target) return;
      active.acted = true;
      const a = target.annotation;
      pressed.get(a.id)?.add(type);
      if (type === "knew_this") entries.get(a.id)?.segments.forEach((m) => m.classList.add(KNOWN_CLASS));
      if (type === "report_wrong") {
        const explanation = shown.get(a.id);
        if (!explanation) return;
        shown.delete(a.id);
        card.setExplanation("reported");
        emit({ ...event(type, a), explanation_id: explanation.id });
        return;
      }
      emit(event(type, a));
    },
    onDismiss: () => close(true, true),
    onShift: (shift) => {
      const target = active && lookup(active.id);
      if (!target) return;
      loadInto(target.annotation, shift);
    },
    labels: options.labels,
    demo: options.actions === "demo" ? options.demoAction ?? { label: "Try it on any article", onClick: () => undefined } : undefined,
  }, inline);
  card.enableShift(Boolean(options.loadShifted));

  /** What a card shows and what it hangs from: a span's first segment or a paragraph marker. */
  function lookup(id: string): { annotation: CardAnnotation; anchor: HTMLElement } | null {
    const entry = entries.get(id);
    const first = entry?.segments[0];
    if (entry && first) return { annotation: entry.annotation, anchor: first };
    const marker = markers.get(id);
    if (marker) return { annotation: paragraphCard(marker.item), anchor: marker.button };
    return null;
  }
  const primary = (id: string) => lookup(id)?.anchor;

  const signals = new Signals(root, {
    paragraphAttribute: attr,
    emit: (e) => emit(e),
    conceptIn: (range) => {
      for (const entry of entries.values()) {
        if (entry.segments.some((m) => range.intersectsNode(m))) return entry.annotation.concept_id;
      }
      for (const prompt of prompts.values()) {
        if (prompt.segments.some((m) => range.intersectsNode(m))) return prompt.item.concept_id;
      }
      return null;
    },
    hasMarks: (paragraphId) =>
      [...entries.values()].some((e) => e.annotation.paragraph_id === paragraphId) ||
      [...prompts.values()].some((p) => p.item.paragraph_id === paragraphId),
  });

  function setHovered(id: string | null): void {
    if (hovered === id) return;
    hovered = id;
    options.onHover?.(id);
  }

  function placement(): { mode: CardMode; box: SidenoteBox | null } {
    if (inline) return { mode: "inline", box: null };
    const narrow = view?.matchMedia?.(SHEET_QUERY).matches ?? false;
    if (narrow || lastPointer === "touch") return { mode: "sheet", box: null };
    const box = options.sidenote?.() ?? null;
    return box ? { mode: "sidenote", box } : { mode: "float", box: null };
  }

  /** `quiet`: the host opened it (inline), so its status line doesn't announce. */
  function openCard(id: string, pinned: boolean, focus = false, quiet = false): void {
    clearTimeout(openTimer);
    clearTimeout(closeTimer);
    const target = lookup(id);
    if (!target) return;
    const { annotation, anchor: mark } = target;
    const changed = active?.id !== id;
    if (active && changed) {
      primary(active.id)?.setAttribute("aria-expanded", "false");
      dismissed(active); // moved on to another note without acting on this one
    }
    pressed.set(id, pressed.get(id) ?? new Set());
    active = changed || !active
      ? { id, pinned, acted: false }
      : { ...active, pinned: pinned || active.pinned };
    if (changed || !card.isOpen) {
      card.setQuiet(quiet);
      card.fill(annotation, pressed.get(id) ?? new Set());
      if (!pressed.get(id)?.has("report_wrong")) loadInto(annotation);
      const { mode, box } = placement();
      card.show(mark, mode, box, pinned);
      mark.setAttribute("aria-expanded", "true");
      emit(event("explain_opened", annotation));
      options.onActive?.(id);
    }
    if (focus || card.el.dataset.mode === "sheet") card.el.focus({ preventScroll: true });
  }

  /** A span card opened on purpose and closed without an action (DESIGN §9). Paragraph cards
   * have no concept, so the API would ignore it; hover peeks never count. */
  function dismissed(a: Active): void {
    const entry = entries.get(a.id);
    if (!entry || !a.pinned || a.acted) return;
    emit(event("annotation_dismissed", entry.annotation));
  }

  function loadInto(annotation: CardAnnotation, shift: -1 | 0 | 1 = 0): void {
    const shifted = options.loadShifted;
    const load: ((a: CardAnnotation) => Promise<Explanation>) | undefined =
      shift && shifted ? (a) => shifted(a, shift as -1 | 1) : options.loadExplanation;
    if (!load) return;
    const token = ++loadToken;
    const settle = (result: Explanation | null) => {
      if (token !== loadToken || active?.id !== annotation.id) return;
      if (result?.kind === "verified") shown.set(annotation.id, result);
      card.setExplanation(result ?? { id: "", kind: "definition", background: null, author_says: null });
      options.onCardReady?.(annotation.id);
    };
    card.setShift(shift);
    card.setExplanation("loading");
    load(annotation).then(settle, () => settle(null));
  }

  /** `byReader`: the reader closed it (Escape, outside click, toggle), as opposed to an update,
   * a host call or destroy. Only those can count as a dismissal. */
  function close(returnFocus = false, byReader = false): void {
    clearTimeout(openTimer);
    clearTimeout(closeTimer);
    if (!active) return;
    const mark = primary(active.id);
    mark?.setAttribute("aria-expanded", "false");
    if (byReader) dismissed(active);
    card.hide();
    active = null;
    options.onActive?.(null);
    if (returnFocus) mark?.focus({ preventScroll: true });
  }

  const scheduleClose = () => {
    clearTimeout(closeTimer);
    const wait = card.el.dataset.mode === "sidenote" ? SIDENOTE_CLOSE_MS : closeDelay;
    closeTimer = setTimeout(() => close(), wait);
  };

  const pointerType = (e: Event) => (e as PointerEvent).pointerType || "mouse";

  const onPointerOver = (e: Event) => {
    const id = markId(e.target as Element);
    if (!id || !entries.has(id)) return;
    setHovered(id);
    if (inline || pointerType(e) === "touch") return;
    clearTimeout(closeTimer);
    if (active?.id === id) return;
    clearTimeout(openTimer);
    openTimer = setTimeout(() => openCard(id, false), hoverDelay);
  };

  const onPointerOut = (e: Event) => {
    const from = markId(e.target as Element);
    const to = (e as PointerEvent).relatedTarget as Node | null;
    if (!from || (to instanceof Element && markId(to) === from)) return;
    setHovered(null);
    if (inline || pointerType(e) === "touch" || card.contains(to)) return;
    clearTimeout(openTimer);
    if (active && !active.pinned) scheduleClose();
  };

  const onPointerDown = (e: Event) => {
    lastPointer = pointerType(e);
  };

  const onClick = (e: Event) => {
    const target = e.target as Element;
    const marker = target.closest?.(`.${PMARK_CLASS}`);
    if (marker && root.contains(marker)) {
      const mid = (marker as HTMLElement).dataset.rlMarker;
      if (!mid || !markers.has(mid)) return;
      e.preventDefault();
      // A keyboard "click" (Enter / Space) has no pointer position: focus moves into the card.
      const fromKeyboard = (e as MouseEvent).detail === 0;
      if (fromKeyboard) lastPointer = "keyboard";
      if (active?.id === mid && active.pinned) close(fromKeyboard, true);
      else openCard(mid, true, fromKeyboard);
      return;
    }
    const id = markId(target);
    if (!id || !entries.has(id)) return;
    e.preventDefault();
    if (active?.id === id && active.pinned) {
      if (!inline) close(false, true);
    } else openCard(id, true);
  };

  const onKeyDown = (e: KeyboardEvent) => {
    const id = markId(e.target as Element);
    if (!id || !entries.has(id) || (e.key !== "Enter" && e.key !== " ")) return;
    e.preventDefault();
    lastPointer = "keyboard";
    openCard(id, true, true);
  };

  const onFocusIn = (e: FocusEvent) => setHovered(markId(e.target as Element));
  const onFocusOutRoot = (e: FocusEvent) => {
    const to = e.relatedTarget as Element | null;
    if (!to || !markId(to)) setHovered(null);
  };

  /** Focus trap: Tab cycles within the card; Escape closes and returns focus to the mark. */
  const onCardKeyDown = (e: KeyboardEvent) => {
    if (!active) return;
    if (e.key === "Escape") {
      e.preventDefault();
      if (inline) primary(active.id)?.focus({ preventScroll: true });
      else close(true, true);
      return;
    }
    if (e.key !== "Tab" || inline) return;
    const items = card.focusables();
    const first = items[0];
    const last = items[items.length - 1];
    if (!first || !last) return;
    const current = doc.activeElement;
    if (e.shiftKey && (current === first || current === card.el)) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && (current === last || current === card.el)) {
      e.preventDefault();
      first.focus();
    }
  };

  const onCardPointerEnter = () => clearTimeout(closeTimer);
  const onCardPointerLeave = (e: Event) => {
    if (!inline && pointerType(e) !== "touch" && active && !active.pinned) scheduleClose();
  };

  const onDocPointerDown = (e: Event) => {
    const t = e.target as Node;
    if (inline || !active || card.contains(t)) return;
    // Marks and markers toggle their own card on click.
    if (t instanceof Element && (markId(t) || t.closest(`.${PMARK_CLASS}`))) return;
    close(false, true);
  };

  const onDocKeyDown = (e: KeyboardEvent) => {
    if (!inline && e.key === "Escape" && active && !card.contains(e.target as Node)) close(false, true);
  };

  root.addEventListener("pointerover", onPointerOver);
  root.addEventListener("pointerout", onPointerOut);
  root.addEventListener("pointerdown", onPointerDown);
  root.addEventListener("click", onClick);
  root.addEventListener("keydown", onKeyDown);
  root.addEventListener("focusin", onFocusIn);
  root.addEventListener("focusout", onFocusOutRoot);
  card.el.addEventListener("keydown", onCardKeyDown);
  card.el.addEventListener("pointerenter", onCardPointerEnter);
  card.el.addEventListener("pointerleave", onCardPointerLeave);
  doc.addEventListener("pointerdown", onDocPointerDown);
  doc.addEventListener("keydown", onDocKeyDown);

  const scopes = () => {
    const map = new Map<string, HTMLElement>();
    root.querySelectorAll<HTMLElement>(`[${attr}]`).forEach((el) => {
      const key = el.getAttribute(attr);
      if (key && !map.has(key)) map.set(key, el);
    });
    return map;
  };

  /** The highlight style for the reader's level; a missing level (older APIs) means new. */
  function setLevel(segments: HTMLElement[], a: CardAnnotation): void {
    const level = a.level === "refresher" ? "refresher" : "new";
    for (const m of segments) {
      m.classList.toggle(`${MARK_CLASS}--new`, level === "new");
      m.classList.toggle(`${MARK_CLASS}--refresher`, level === "refresher");
    }
  }

  function removeEntries(ids: string[]): void {
    for (const id of ids) {
      const entry = entries.get(id);
      if (!entry) continue;
      unwrap(root, entry.segments);
      entries.delete(id);
    }
  }

  async function update(
    annotations: readonly AnyAnnotation[],
    { reader: nextReader }: UpdateOptions = {},
  ): Promise<UpdateResult> {
    const gen = ++generation;
    const readerChanged = nextReader !== undefined && nextReader !== reader;
    if (readerChanged) {
      reader = nextReader;
      for (const set of pressed.values()) set.clear();
      shown.clear();
      answered.clear();
      for (const entry of entries.values()) {
        entry.segments.forEach((m) => m.classList.remove(KNOWN_CLASS));
      }
    }
    const spans = annotations.filter((a): a is CardAnnotation => a.kind === "span");
    const next = new Map(spans.map((a) => [a.id, a]));
    const leaving = [...entries.keys()].filter((id) => {
      const a = next.get(id);
      return !a || !sameAnchor(a, entries.get(id)!.annotation);
    });
    if (active && leaving.includes(active.id)) close();
    if (linked && leaving.includes(linked)) highlight(null);
    // Prompts step aside while spans move (a prompt's term is never a span's), then return.
    removePrompts(readerChanged ? [...prompts.keys()] : []);
    if (readerChanged) released.splice(0).forEach((el) => el.remove());
    // An answered prompt that's no longer listed frees its term (the refetched notes may make it
    // a span, decision 46d) but keeps its "Noted, thanks." chip until the page goes.
    const listed = new Set(annotations.filter((a) => a.kind === "prompt").map((a) => a.id));
    releaseAnswered([...prompts.keys()].filter((id) => answered.has(id) && !listed.has(id)));

    if (leaving.length) {
      for (const id of leaving) {
        for (const m of entries.get(id)!.segments) {
          m.classList.remove(ENTER_CLASS);
          m.classList.add(LEAVE_CLASS);
          m.removeAttribute("tabindex");
          m.removeAttribute("role");
        }
      }
      if (leaveMs) await sleep(leaveMs);
      if (gen !== generation) return snapshot(annotations);
      removeEntries(leaving);
    }
    syncMarkers(annotations.filter((a): a is ParagraphMarker => a.kind === "paragraph"));

    // Kept marks stay still and pick up fresh data (scores and debug numbers move with the
    // persona); only the notes that differ animate.
    for (const [id, entry] of entries) {
      const a = next.get(id);
      if (a) {
        entry.annotation = a;
        setLevel(entry.segments, a); // the same term can be new to one reader, a refresher to another
      }
      entry.segments.forEach((m) => m.classList.remove(ENTER_CLASS));
    }
    // An open card shows the new data, and its explanation for the new reader (hosts cache,
    // so the same reader's explanation comes back at once).
    const open = active && entries.get(active.id);
    if (open && card.isOpen) {
      card.fill(open.annotation, pressed.get(open.annotation.id) ?? new Set());
      if (!pressed.get(open.annotation.id)?.has("report_wrong")) loadInto(open.annotation);
    }

    const paragraphScopes = scopes();
    const added: Entry[] = [];
    for (const a of next.values()) {
      if (entries.has(a.id)) continue;
      const range = locate(root, paragraphScopes.get(a.paragraph_id), a.anchor);
      const segments = range ? wrapRange(root, range, a.id) : [];
      const first = segments[0];
      if (!range || !first) continue;
      setLevel(segments, a);
      first.tabIndex = 0;
      first.setAttribute("role", "button");
      first.setAttribute("aria-haspopup", "dialog");
      first.setAttribute("aria-expanded", "false");
      first.setAttribute("aria-controls", card.id);
      const entry = { annotation: a, segments, start: range.start };
      entries.set(a.id, entry);
      pressed.set(a.id, pressed.get(a.id) ?? new Set());
      added.push(entry);
    }
    added
      .sort((x, y) => x.start - y.start)
      .forEach((entry, i) => {
        for (const m of entry.segments) {
          m.style.animationDelay = `${i * staggerMs}ms`;
          m.classList.add(ENTER_CLASS);
          m.addEventListener("animationend", () => m.classList.remove(ENTER_CLASS), { once: true });
        }
      });
    syncPrompts(annotations.filter((a): a is PromptAnnotation => a.kind === "prompt"));
    return snapshot(annotations);
  }

  function snapshot(annotations: readonly AnyAnnotation[]): UpdateResult {
    const resolved = [...entries.values()].sort((x, y) => x.start - y.start).map((e) => e.annotation.id);
    const placed = new Set([...resolved, ...markers.keys(), ...prompts.keys()]);
    const unresolved = annotations
      .filter((a) => a.kind !== "preread" && !placed.has(a.id))
      .map((a) => a.id);
    return { resolved, unresolved };
  }

  /** Paragraph markers: keep those still wanted, add new ones at the start of their paragraph. */
  function syncMarkers(items: ParagraphMarker[]): void {
    const wanted = new Map(items.map((m) => [m.id, m]));
    for (const [id, m] of markers) {
      if (wanted.get(id)?.paragraph_id === m.item.paragraph_id) {
        m.item = wanted.get(id)!;
        continue;
      }
      if (active?.id === id) close();
      m.button.parentElement?.removeAttribute(HAS_MARKER_ATTR);
      m.button.remove();
      markers.delete(id);
    }
    const paragraphScopes = scopes();
    for (const item of items) {
      if (markers.has(item.id)) continue;
      const paragraph = paragraphScopes.get(item.paragraph_id);
      if (!paragraph) continue;
      const button = createMarker(doc, item, card.id);
      paragraph.setAttribute(HAS_MARKER_ATTR, "");
      paragraph.prepend(button);
      markers.set(item.id, { item, button });
      pressed.set(item.id, pressed.get(item.id) ?? new Set());
    }
  }

  function removePrompts(ids: string[]): void {
    for (const id of ids) {
      const p = prompts.get(id);
      if (!p) continue;
      p.ask.el.remove();
      unwrap(root, p.segments);
      prompts.delete(id);
    }
  }

  function releaseAnswered(ids: string[]): void {
    for (const id of ids) {
      const p = prompts.get(id);
      if (!p) continue;
      unwrap(root, p.segments);
      prompts.delete(id);
      released.push(p.ask.el);
    }
  }

  /** "Know this?" chips after their terms. Answered ones stay answered for this reader. */
  function syncPrompts(items: PromptAnnotation[]): void {
    const wanted = new Set(items.map((p) => p.id));
    removePrompts([...prompts.keys()].filter((id) => !wanted.has(id)));
    const paragraphScopes = scopes();
    for (const item of items) {
      if (prompts.has(item.id)) continue;
      const range = locate(root, paragraphScopes.get(item.paragraph_id), item.anchor);
      const segments = range ? wrapRange(root, range, item.id) : [];
      const last = segments[segments.length - 1];
      if (!last) continue;
      segments.forEach((m) => m.classList.add(ASK_MARK_CLASS));
      const ask = createAsk(
        doc,
        item,
        async (prompt, known) => {
          await options.onAnswer?.(prompt, known);
          answered.add(prompt.id);
        },
        answered.has(item.id),
      );
      last.after(ask.el);
      prompts.set(item.id, { item, segments, ask });
    }
  }

  function highlight(id: string | null): void {
    if (linked) entries.get(linked)?.segments.forEach((m) => m.classList.remove(LINK_CLASS));
    linked = id && entries.has(id) ? id : null;
    if (linked) entries.get(linked)?.segments.forEach((m) => m.classList.add(LINK_CLASS));
  }

  function open(id: string, { focus = false } = {}): void {
    const mark = primary(id);
    if (!mark) return;
    if (!inline) mark.scrollIntoView?.({ block: "center", behavior: reducedMotion ? "auto" : "smooth" });
    if (focus) lastPointer = "keyboard";
    openCard(id, true, focus, Boolean(inline) && !focus);
  }

  return {
    update,
    highlight,
    open,
    close: () => close(),
    flush: () => signals.flush(),
    destroy() {
      generation++;
      close();
      signals.destroy();
      root.removeEventListener("pointerover", onPointerOver);
      root.removeEventListener("pointerout", onPointerOut);
      root.removeEventListener("pointerdown", onPointerDown);
      root.removeEventListener("click", onClick);
      root.removeEventListener("keydown", onKeyDown);
      root.removeEventListener("focusin", onFocusIn);
      root.removeEventListener("focusout", onFocusOutRoot);
      doc.removeEventListener("pointerdown", onDocPointerDown);
      doc.removeEventListener("keydown", onDocKeyDown);
      card.destroy();
      removeUi(root);
      root.querySelectorAll(`[${HAS_MARKER_ATTR}]`).forEach((el) => el.removeAttribute(HAS_MARKER_ATTR));
      unwrap(root);
      entries.clear();
      markers.clear();
      prompts.clear();
    },
  };
}

export interface MountedAnnotator extends UpdateResult {
  annotator: Annotator;
  destroy(): void;
}

/** One-shot convenience: mark these annotations with no entrance animation. */
export function mount(
  root: HTMLElement,
  annotations: readonly AnyAnnotation[],
  options: AnnotatorOptions = {},
): Promise<MountedAnnotator> {
  const annotator = createAnnotator(root, { leaveMs: 0, staggerMs: 0, ...options });
  return annotator.update(annotations).then((r) => ({ ...r, annotator, destroy: annotator.destroy }));
}

function sameAnchor(a: CardAnnotation, b: CardAnnotation): boolean {
  return (
    a.paragraph_id === b.paragraph_id &&
    a.anchor.exact === b.anchor.exact &&
    a.anchor.prefix === b.anchor.prefix &&
    a.anchor.suffix === b.anchor.suffix
  );
}

/**
 * Root-level offsets for an anchor: inside its paragraph when the host marks paragraphs,
 * else anywhere in the root (the extension case), using the article offset as a tie-breaker.
 * Offsets count article text only (indexText skips the annotator's own controls).
 */
function locate(root: HTMLElement, scope: HTMLElement | undefined, anchor: Anchor): TextRange | null {
  const index = indexText(root);
  if (scope) {
    const local = resolveInText(indexText(scope).text, anchor);
    const first = index.nodes.findIndex((n) => scope.contains(n));
    if (local && first !== -1) {
      const offset = index.starts[first] as number;
      return { start: offset + local.start, end: offset + local.end };
    }
  }
  return resolveInText(index.text, anchor, anchor.start);
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function event(type: AnnotatorEventType, a: CardAnnotation): AnnotatorEvent {
  return {
    type,
    annotation_id: a.id,
    concept_id: a.concept_id,
    at: new Date().toISOString(),
    ...(a.kind === "paragraph" ? { paragraph_id: a.paragraph_id } : {}),
  };
}
