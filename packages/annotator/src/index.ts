/**
 * Shared annotation overlay used by the web app and the extension (DESIGN §9).
 * Framework-free: mount() wraps resolved spans in marks and drives one shared card.
 */

import { indexText, resolveInText, type TextRange } from "./anchor";
import { Card } from "./card";
import { markId, unwrapAll, wrapRange } from "./mark";
import { injectStyles } from "./styles";
import type { AnnotatorEvent, AnnotatorEventType, CardAnnotation } from "./types";

export type * from "./types";
export { CARD_LABEL } from "./card";
export { normalizeWhitespace, resolveInText } from "./anchor";

export const ANNOTATOR_VERSION = "0.2.0";

export interface MountOptions {
  /** Interaction events. Batching to /v1/events arrives with the reader model. */
  onEvent?: (event: AnnotatorEvent) => void;
  /** Attribute naming a paragraph element, used to scope anchor search. */
  paragraphAttribute?: string;
  hoverDelayMs?: number;
  closeDelayMs?: number;
}

export interface MountedAnnotator {
  /** Annotation ids that were found and marked. */
  resolved: string[];
  /** Annotation ids that were skipped (not found, overlapping, or not a span). */
  unresolved: string[];
  destroy(): void;
}

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function mount(
  root: HTMLElement,
  annotations: readonly CardAnnotation[],
  options: MountOptions = {},
): MountedAnnotator {
  const doc = root.ownerDocument;
  const view = doc.defaultView;
  const attr = options.paragraphAttribute ?? "data-rl-paragraph";
  const hoverDelay = options.hoverDelayMs ?? 120;
  const closeDelay = options.closeDelayMs ?? 220;
  const emit = options.onEvent ?? (() => {});
  injectStyles(doc);

  const byId = new Map<string, CardAnnotation>();
  const marks = new Map<string, HTMLElement[]>();
  const pressed = new Map<string, Set<AnnotatorEventType>>();
  const resolved: string[] = [];
  const unresolved: string[] = [];

  const card = new Card(doc, {
    onAction: (type) => {
      if (!active) return;
      const a = byId.get(active.id);
      if (!a) return;
      pressed.get(a.id)?.add(type);
      if (type === "knew_this") marks.get(a.id)?.forEach((m) => m.classList.add("rl-mark--known"));
      emit(event(type, a));
    },
  });

  const scopes = new Map<string, HTMLElement>();
  root.querySelectorAll<HTMLElement>(`[${attr}]`).forEach((el) => {
    const key = el.getAttribute(attr);
    if (key && !scopes.has(key)) scopes.set(key, el);
  });

  for (const a of annotations) {
    const range = a.kind === "span" ? locate(root, scopes.get(a.paragraph_id), a) : null;
    const segments = range ? wrapRange(root, range, a.id) : [];
    const first = segments[0];
    if (!first) {
      unresolved.push(a.id);
      continue;
    }
    first.tabIndex = 0;
    first.setAttribute("role", "button");
    first.setAttribute("aria-haspopup", "dialog");
    first.setAttribute("aria-expanded", "false");
    first.setAttribute("aria-controls", card.id);
    byId.set(a.id, a);
    marks.set(a.id, segments);
    pressed.set(a.id, new Set());
    resolved.push(a.id);
  }

  let active: { id: string; pinned: boolean } | null = null;
  let openTimer: ReturnType<typeof setTimeout> | undefined;
  let closeTimer: ReturnType<typeof setTimeout> | undefined;

  const primary = (id: string) => marks.get(id)?.[0];

  function open(id: string, pinned: boolean, focus = false): void {
    clearTimeout(openTimer);
    clearTimeout(closeTimer);
    const a = byId.get(id);
    const mark = primary(id);
    if (!a || !mark) return;
    const changed = active?.id !== id;
    if (active && changed) primary(active.id)?.setAttribute("aria-expanded", "false");
    active = { id, pinned: pinned || (!changed && !!active?.pinned) };
    if (changed || !card.isOpen) {
      card.fill(a, pressed.get(id) ?? new Set());
      card.show(mark);
      mark.setAttribute("aria-expanded", "true");
      emit(event("explain_opened", a));
    }
    if (focus) card.el.focus();
  }

  function close(returnFocus = false): void {
    clearTimeout(openTimer);
    clearTimeout(closeTimer);
    if (!active) return;
    const mark = primary(active.id);
    mark?.setAttribute("aria-expanded", "false");
    card.hide();
    active = null;
    if (returnFocus) mark?.focus();
  }

  const scheduleClose = () => {
    clearTimeout(closeTimer);
    closeTimer = setTimeout(() => close(), closeDelay);
  };

  const isTouch = (e: Event) => (e as PointerEvent).pointerType === "touch";

  const onPointerOver = (e: Event) => {
    if (isTouch(e)) return;
    const id = markId(e.target as Element);
    if (!id) return;
    clearTimeout(closeTimer);
    if (active?.id === id) return;
    clearTimeout(openTimer);
    openTimer = setTimeout(() => open(id, false), hoverDelay);
  };

  const onPointerOut = (e: Event) => {
    if (isTouch(e)) return;
    const from = markId(e.target as Element);
    const to = (e as PointerEvent).relatedTarget as Node | null;
    if (!from || (to instanceof Element && markId(to) === from) || card.contains(to)) return;
    clearTimeout(openTimer);
    if (active && !active.pinned) scheduleClose();
  };

  const onClick = (e: Event) => {
    const id = markId(e.target as Element);
    if (!id || !byId.has(id)) return;
    e.preventDefault();
    if (active?.id === id && active.pinned) close();
    else open(id, true);
  };

  const onKeyDown = (e: KeyboardEvent) => {
    const id = markId(e.target as Element);
    if (!id || !byId.has(id) || (e.key !== "Enter" && e.key !== " ")) return;
    e.preventDefault();
    open(id, true, true);
  };

  const onCardKeyDown = (e: KeyboardEvent) => {
    if (!active) return;
    const mark = primary(active.id);
    if (e.key === "Escape") {
      e.preventDefault();
      close(true);
      return;
    }
    if (e.key !== "Tab" || !mark) return;
    const items = Array.from(card.el.querySelectorAll<HTMLElement>("button"));
    const target = e.target as HTMLElement;
    const atStart = target === card.el || target === items[0];
    const atEnd = target === items[items.length - 1];
    if (e.shiftKey && atStart) {
      e.preventDefault();
      close(true);
    } else if (!e.shiftKey && atEnd) {
      e.preventDefault();
      close();
      const next = nextFocusable(doc, mark, card.el);
      if (next) next.focus();
      else mark.focus();
    }
  };

  const onCardPointerEnter = () => clearTimeout(closeTimer);
  const onCardPointerLeave = (e: Event) => {
    if (!isTouch(e) && active && !active.pinned) scheduleClose();
  };

  const onDocPointerDown = (e: Event) => {
    const t = e.target as Node;
    if (!active || card.contains(t) || (t instanceof Element && markId(t))) return;
    close();
  };

  const onDocKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Escape" && active && !card.contains(e.target as Node)) close();
  };

  const onFocusOut = (e: FocusEvent) => {
    const to = e.relatedTarget as Node | null;
    if (!active || !to || card.contains(to)) return;
    if (to instanceof Element && markId(to) === active.id) return;
    close();
  };

  const onResize = () => close();

  root.addEventListener("pointerover", onPointerOver);
  root.addEventListener("pointerout", onPointerOut);
  root.addEventListener("click", onClick);
  root.addEventListener("keydown", onKeyDown);
  card.el.addEventListener("keydown", onCardKeyDown);
  card.el.addEventListener("pointerenter", onCardPointerEnter);
  card.el.addEventListener("pointerleave", onCardPointerLeave);
  card.el.addEventListener("focusout", onFocusOut);
  doc.addEventListener("pointerdown", onDocPointerDown);
  doc.addEventListener("keydown", onDocKeyDown);
  view?.addEventListener("resize", onResize);

  return {
    resolved,
    unresolved,
    destroy() {
      close();
      root.removeEventListener("pointerover", onPointerOver);
      root.removeEventListener("pointerout", onPointerOut);
      root.removeEventListener("click", onClick);
      root.removeEventListener("keydown", onKeyDown);
      doc.removeEventListener("pointerdown", onDocPointerDown);
      doc.removeEventListener("keydown", onDocKeyDown);
      view?.removeEventListener("resize", onResize);
      card.destroy();
      unwrapAll(root);
    },
  };
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

function nextFocusable(doc: Document, after: Element, exclude: Element): HTMLElement | null {
  for (const el of Array.from(doc.querySelectorAll<HTMLElement>(FOCUSABLE))) {
    if (exclude.contains(el) || after.contains(el)) continue;
    if (after.compareDocumentPosition(el) & 4 /* DOCUMENT_POSITION_FOLLOWING */) return el;
  }
  return null;
}

function event(type: AnnotatorEventType, a: CardAnnotation): AnnotatorEvent {
  return { type, annotation_id: a.id, concept_id: a.concept_id, at: new Date().toISOString() };
}
