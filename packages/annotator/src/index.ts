/**
 * Shared annotation overlay used by the web app and the extension (DESIGN §9).
 * Framework-free: an Annotator wraps resolved spans in marks, drives one shared card, and
 * diffs updates so a persona or density change visibly swaps only the notes that differ.
 */

import { indexText, resolveInText, type TextRange } from "./anchor";
import { Card, SHEET_QUERY, type CardMode } from "./card";
import { MARK_CLASS, markId, unwrap, wrapRange } from "./mark";
import { injectStyles } from "./styles";
import type { AnnotatorEvent, AnnotatorEventType, CardAnnotation } from "./types";

export type * from "./types";
export { CARD_LABEL } from "./card";
export { normalizeWhitespace, resolveInText } from "./anchor";

export const ANNOTATOR_VERSION = "0.3.0";

export interface AnnotatorOptions {
  /** Interaction events. Batching to /v1/events arrives with the reader model. */
  onEvent?: (event: AnnotatorEvent) => void;
  /** A mark is hovered or focused (id), or no longer is (null). For linked UI like a rail. */
  onHover?: (id: string | null) => void;
  /** The card opened for an annotation (id) or closed (null). */
  onActive?: (id: string | null) => void;
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
  /** Annotation ids that are marked, in document order. */
  resolved: string[];
  /** Annotation ids that were skipped (not found, overlapping, or not a span). */
  unresolved: string[];
}

export interface Annotator {
  update(annotations: readonly CardAnnotation[]): Promise<UpdateResult>;
  /** Emphasise one annotation's mark (e.g. while its rail chip is hovered); null clears. */
  highlight(id: string | null): void;
  /** Open an annotation's card, scrolling it into view; `focus` moves focus into the card. */
  open(id: string, options?: { focus?: boolean }): void;
  close(): void;
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
  injectStyles(doc);

  const entries = new Map<string, Entry>();
  const pressed = new Map<string, Set<AnnotatorEventType>>();
  let active: { id: string; pinned: boolean } | null = null;
  let linked: string | null = null;
  let hovered: string | null = null;
  let generation = 0;
  let openTimer: ReturnType<typeof setTimeout> | undefined;
  let closeTimer: ReturnType<typeof setTimeout> | undefined;
  let lastPointer = "mouse";

  const card = new Card(doc, {
    onAction: (type) => {
      const entry = active && entries.get(active.id);
      if (!entry) return;
      pressed.get(entry.annotation.id)?.add(type);
      if (type === "knew_this") entry.segments.forEach((m) => m.classList.add(KNOWN_CLASS));
      emit(event(type, entry.annotation));
    },
    onDismiss: () => close(true),
  });

  const primary = (id: string) => entries.get(id)?.segments[0];

  function setHovered(id: string | null): void {
    if (hovered === id) return;
    hovered = id;
    options.onHover?.(id);
  }

  function cardMode(): CardMode {
    const narrow = view?.matchMedia?.(SHEET_QUERY).matches ?? false;
    return narrow || lastPointer === "touch" ? "sheet" : "float";
  }

  function openCard(id: string, pinned: boolean, focus = false): void {
    clearTimeout(openTimer);
    clearTimeout(closeTimer);
    const entry = entries.get(id);
    const mark = primary(id);
    if (!entry || !mark) return;
    const changed = active?.id !== id;
    if (active && changed) primary(active.id)?.setAttribute("aria-expanded", "false");
    active = { id, pinned: pinned || (!changed && !!active?.pinned) };
    if (changed || !card.isOpen) {
      card.fill(entry.annotation, pressed.get(id) ?? new Set());
      card.show(mark, cardMode());
      mark.setAttribute("aria-expanded", "true");
      emit(event("explain_opened", entry.annotation));
      options.onActive?.(id);
    }
    if (focus || card.el.dataset.mode === "sheet") card.el.focus({ preventScroll: true });
  }

  function close(returnFocus = false): void {
    clearTimeout(openTimer);
    clearTimeout(closeTimer);
    if (!active) return;
    const mark = primary(active.id);
    mark?.setAttribute("aria-expanded", "false");
    card.hide();
    active = null;
    options.onActive?.(null);
    if (returnFocus) mark?.focus({ preventScroll: true });
  }

  const scheduleClose = () => {
    clearTimeout(closeTimer);
    closeTimer = setTimeout(() => close(), closeDelay);
  };

  const pointerType = (e: Event) => (e as PointerEvent).pointerType || "mouse";

  const onPointerOver = (e: Event) => {
    const id = markId(e.target as Element);
    if (!id || !entries.has(id)) return;
    setHovered(id);
    if (pointerType(e) === "touch") return;
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
    if (pointerType(e) === "touch" || card.contains(to)) return;
    clearTimeout(openTimer);
    if (active && !active.pinned) scheduleClose();
  };

  const onPointerDown = (e: Event) => {
    lastPointer = pointerType(e);
  };

  const onClick = (e: Event) => {
    const id = markId(e.target as Element);
    if (!id || !entries.has(id)) return;
    e.preventDefault();
    if (active?.id === id && active.pinned) close();
    else openCard(id, true);
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
      close(true);
      return;
    }
    if (e.key !== "Tab") return;
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
    if (pointerType(e) !== "touch" && active && !active.pinned) scheduleClose();
  };

  const onDocPointerDown = (e: Event) => {
    const t = e.target as Node;
    if (!active || card.contains(t) || (t instanceof Element && markId(t))) return;
    close();
  };

  const onDocKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Escape" && active && !card.contains(e.target as Node)) close();
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

  function removeEntries(ids: string[]): void {
    for (const id of ids) {
      const entry = entries.get(id);
      if (!entry) continue;
      unwrap(root, entry.segments);
      entries.delete(id);
    }
  }

  async function update(annotations: readonly CardAnnotation[]): Promise<UpdateResult> {
    const gen = ++generation;
    const next = new Map(annotations.filter((a) => a.kind === "span").map((a) => [a.id, a]));
    const leaving = [...entries.keys()].filter((id) => {
      const a = next.get(id);
      return !a || !sameAnchor(a, entries.get(id)!.annotation);
    });
    if (active && leaving.includes(active.id)) close();
    if (linked && leaving.includes(linked)) highlight(null);

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

    // Kept marks stay still and pick up fresh data (scores and debug numbers move with the
    // persona); only the notes that differ animate.
    for (const [id, entry] of entries) {
      const a = next.get(id);
      if (a) entry.annotation = a;
      entry.segments.forEach((m) => m.classList.remove(ENTER_CLASS));
    }

    const paragraphScopes = scopes();
    const added: Entry[] = [];
    for (const a of next.values()) {
      if (entries.has(a.id)) continue;
      const range = locate(root, paragraphScopes.get(a.paragraph_id), a);
      const segments = range ? wrapRange(root, range, a.id) : [];
      const first = segments[0];
      if (!range || !first) continue;
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
    return snapshot(annotations);
  }

  function snapshot(annotations: readonly CardAnnotation[]): UpdateResult {
    const resolved = [...entries.values()].sort((x, y) => x.start - y.start).map((e) => e.annotation.id);
    const marked = new Set(resolved);
    return { resolved, unresolved: annotations.map((a) => a.id).filter((id) => !marked.has(id)) };
  }

  function highlight(id: string | null): void {
    if (linked) entries.get(linked)?.segments.forEach((m) => m.classList.remove(LINK_CLASS));
    linked = id && entries.has(id) ? id : null;
    if (linked) entries.get(linked)?.segments.forEach((m) => m.classList.add(LINK_CLASS));
  }

  function open(id: string, { focus = false } = {}): void {
    const mark = primary(id);
    if (!mark) return;
    mark.scrollIntoView?.({ block: "center", behavior: reducedMotion ? "auto" : "smooth" });
    if (focus) lastPointer = "keyboard";
    openCard(id, true, focus);
  }

  return {
    update,
    highlight,
    open,
    close: () => close(),
    destroy() {
      generation++;
      close();
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
      unwrap(root);
      entries.clear();
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
  annotations: readonly CardAnnotation[],
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
 * Root-level offsets for an annotation: inside its paragraph when the host marks paragraphs,
 * else anywhere in the root (the extension case), using the article offset as a tie-breaker.
 */
function locate(
  root: HTMLElement,
  scope: HTMLElement | undefined,
  a: CardAnnotation,
): TextRange | null {
  if (scope) {
    const local = resolveInText(indexText(scope).text, a.anchor);
    if (local) {
      const before = root.ownerDocument.createRange();
      before.setStart(root, 0);
      before.setEndBefore(scope);
      const offset = before.toString().length;
      return { start: offset + local.start, end: offset + local.end };
    }
  }
  return resolveInText(indexText(root).text, a.anchor, a.anchor.start);
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function event(type: AnnotatorEventType, a: CardAnnotation): AnnotatorEvent {
  return { type, annotation_id: a.id, concept_id: a.concept_id, at: new Date().toISOString() };
}
