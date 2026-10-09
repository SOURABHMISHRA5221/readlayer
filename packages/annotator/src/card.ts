/**
 * The concept card: one shared dialog, floated next to its mark with Floating UI on wide
 * pointers, or shown as a draggable bottom sheet on touch and narrow screens. Filled with
 * textContent only: annotation data is never parsed as HTML.
 */

import {
  arrow,
  autoUpdate,
  computePosition,
  flip,
  offset,
  shift,
} from "@floating-ui/dom";

import type { AnnotationDebug, AnnotatorEventType, CardAnnotation, Explanation } from "./types";

export const CARD_LABEL = "Explanation — not the author's words";
export const BACKGROUND_LABEL = "Background";
export const AUTHOR_LABEL = "What the author is saying";
const REPORTED_TEXT = "Thanks. We've removed this explanation and will review it.";
const LOADING_TEXT = "Writing an explanation and checking it against the article…";

/** What the explanation area shows: nothing (no loader), loading, a result, or reported. */
export type ExplanationState = "none" | "loading" | "reported" | Explanation;
export const SHEET_QUERY = "(max-width: 639px)";
const C = "rl-card";
const GAP_PX = 10;
const EDGE_PX = 12;
const DISMISS_DRAG_PX = 80;
const SVG_NS = "http://www.w3.org/2000/svg";

export type CardMode = "float" | "sheet";

export interface CardHandlers {
  onAction: (type: AnnotatorEventType) => void;
  onDismiss: () => void;
}

let cardCount = 0;

export class Card {
  readonly el: HTMLDivElement;
  private readonly scrim: HTMLDivElement;
  private readonly arrowEl: HTMLDivElement;
  private readonly domain: HTMLParagraphElement;
  private readonly title: HTMLParagraphElement;
  private readonly definition: HTMLParagraphElement;
  private readonly prereqs: HTMLDivElement;
  private readonly prereqList: HTMLUListElement;
  private readonly debug: HTMLDListElement;
  private readonly explain: HTMLDivElement;
  private readonly skeleton: HTMLDivElement;
  private readonly background: HTMLParagraphElement;
  private readonly authorSays: HTMLParagraphElement;
  private readonly status: HTMLParagraphElement;
  private readonly report: HTMLButtonElement;
  private readonly buttons: HTMLButtonElement[];
  private stopAutoUpdate: (() => void) | null = null;
  private mode: CardMode = "float";

  constructor(
    private readonly doc: Document,
    handlers: CardHandlers,
  ) {
    const id = `rl-card-${++cardCount}`;
    this.el = el(doc, "div", C);
    Object.assign(this.el, { id, hidden: true, tabIndex: -1 });
    this.el.setAttribute("role", "dialog");
    this.el.setAttribute("aria-labelledby", `${id}-title`);
    this.el.setAttribute("aria-describedby", `${id}-def`);

    this.scrim = el(doc, "div", "rl-scrim");
    this.scrim.hidden = true;
    this.scrim.addEventListener("click", handlers.onDismiss);

    const handle = el(doc, "div", `${C}__handle`);
    handle.setAttribute("aria-hidden", "true");
    this.enableDrag(handle, handlers.onDismiss);

    this.arrowEl = el(doc, "div", `${C}__arrow`);
    this.arrowEl.setAttribute("aria-hidden", "true");

    this.domain = el(doc, "p", `${C}__domain`);
    this.title = el(doc, "p", `${C}__title`);
    this.title.id = `${id}-title`;
    this.definition = el(doc, "p", `${C}__def`);
    this.definition.id = `${id}-def`;

    this.prereqs = el(doc, "div", `${C}__prereqs`);
    const prereqLabel = el(doc, "p", `${C}__prereq-label`);
    prereqLabel.textContent = "Before this";
    prereqLabel.id = `${id}-prereq`;
    this.prereqList = el(doc, "ul", `${C}__chips`);
    this.prereqList.setAttribute("aria-labelledby", prereqLabel.id);
    this.prereqs.append(prereqLabel, this.prereqList);

    this.debug = el(doc, "dl", `${C}__debug`);

    // Verified explanation: Background (the reader's frame) and the author's claim, kept apart.
    this.explain = el(doc, "div", `${C}__explain`);
    this.skeleton = el(doc, "div", `${C}__skeleton`);
    this.skeleton.setAttribute("aria-hidden", "true");
    this.skeleton.append(
      ...[0, 1, 2].map(() => el(doc, "span", `${C}__skeleton-line`)),
    );
    this.background = el(doc, "p", `${C}__text`);
    this.background.id = `${id}-bg`;
    this.authorSays = el(doc, "p", `${C}__text`);
    this.explain.append(
      this.skeleton,
      section(doc, BACKGROUND_LABEL, this.background),
      section(doc, AUTHOR_LABEL, this.authorSays),
    );
    // Announces loading and the report confirmation to screen readers.
    this.status = el(doc, "p", `${C}__status`);
    this.status.setAttribute("role", "status");

    const footer = el(doc, "div", `${C}__footer`);
    const knew = button(doc, "knew_this", "rl-btn rl-btn--ghost");
    knew.textContent = "Knew this";
    const helpful = button(doc, "explain_helpful", "rl-btn rl-btn--icon");
    helpful.setAttribute("aria-label", "Helpful");
    helpful.title = "Helpful";
    helpful.append(thumbIcon(doc));
    this.report = button(doc, "report_wrong", "rl-btn rl-btn--ghost rl-btn--quiet");
    this.report.textContent = "This is wrong";
    this.buttons = [knew, this.report, helpful];
    for (const b of this.buttons) {
      b.addEventListener("click", () => {
        b.setAttribute("aria-pressed", "true");
        handlers.onAction(b.dataset.action as AnnotatorEventType);
      });
    }
    const actions = el(doc, "div", `${C}__actions`);
    actions.append(knew, this.report, helpful);
    const note = el(doc, "p", `${C}__note`);
    note.textContent = CARD_LABEL;
    footer.append(actions, note);

    this.el.append(
      handle,
      this.arrowEl,
      this.domain,
      this.title,
      this.definition,
      this.explain,
      this.status,
      this.prereqs,
      this.debug,
      footer,
    );
    doc.body.append(this.scrim, this.el);
  }

  get id(): string {
    return this.el.id;
  }

  get isOpen(): boolean {
    return !this.el.hidden;
  }

  focusables(): HTMLElement[] {
    return this.buttons.filter((b) => !b.disabled && !b.hidden);
  }

  fill(a: CardAnnotation, pressed: ReadonlySet<AnnotatorEventType>): void {
    this.domain.textContent = a.domain ?? "";
    this.domain.hidden = !a.domain;
    this.title.textContent = a.label;
    this.definition.textContent = a.definition;
    const prereqs = a.prerequisites.slice(0, 3);
    this.prereqs.hidden = prereqs.length === 0;
    this.prereqList.replaceChildren(
      ...prereqs.map((label) => {
        const li = el(this.doc, "li", "rl-chip");
        li.textContent = label;
        return li;
      }),
    );
    fillDebug(this.debug, a.debug ?? null);
    for (const b of this.buttons) {
      b.setAttribute("aria-pressed", String(pressed.has(b.dataset.action as AnnotatorEventType)));
    }
    this.setExplanation(pressed.has("report_wrong") ? "reported" : "none");
  }

  /** Swap the explanation area. Definition-only results keep the definition showing. */
  setExplanation(state: ExplanationState): void {
    const verified = typeof state === "object" && state.kind === "verified";
    const loading = state === "loading";
    this.explain.hidden = !(verified || loading);
    this.explain.setAttribute("aria-busy", String(loading));
    this.skeleton.hidden = !loading;
    for (const part of this.explain.querySelectorAll<HTMLElement>(`.${C}__section`)) {
      part.hidden = !verified;
    }
    this.definition.hidden = verified;
    this.el.setAttribute("aria-describedby", verified ? this.background.id : this.definition.id);
    this.background.textContent = verified ? (state.background ?? "") : "";
    this.authorSays.textContent = verified ? (state.author_says ?? "") : "";
    this.status.textContent = state === "reported" ? REPORTED_TEXT : loading ? LOADING_TEXT : "";
    this.status.classList.toggle(`${C}__status--visible`, state === "reported" || loading);
    this.report.disabled = !verified;
    this.report.hidden = state === "none" && this.report.getAttribute("aria-pressed") !== "true";
  }

  show(anchor: HTMLElement, mode: CardMode): void {
    this.stopAutoUpdate?.();
    this.mode = mode;
    this.el.dataset.mode = mode;
    this.el.style.transform = "";
    this.el.hidden = false;
    this.scrim.hidden = mode !== "sheet";
    if (mode === "sheet") {
      Object.assign(this.el.style, { top: "", left: "" });
      return;
    }
    this.stopAutoUpdate = autoUpdate(anchor, this.el, () => void this.place(anchor));
  }

  hide(): void {
    this.stopAutoUpdate?.();
    this.stopAutoUpdate = null;
    this.el.hidden = true;
    this.scrim.hidden = true;
  }

  contains(node: Node | null): boolean {
    return !!node && (this.el.contains(node) || node === this.scrim);
  }

  destroy(): void {
    this.hide();
    this.el.remove();
    this.scrim.remove();
  }

  private async place(anchor: HTMLElement): Promise<void> {
    const { x, y, placement, middlewareData } = await computePosition(anchor, this.el, {
      strategy: "fixed",
      placement: "bottom-start",
      middleware: [
        offset(GAP_PX),
        flip({ padding: EDGE_PX }),
        shift({ padding: EDGE_PX }),
        arrow({ element: this.arrowEl, padding: 14 }),
      ],
    });
    if (this.el.hidden || this.mode !== "float") return;
    Object.assign(this.el.style, { left: `${x}px`, top: `${y}px` });
    this.el.dataset.placement = placement;
    const side = placement.split("-")[0];
    const a = middlewareData.arrow;
    Object.assign(this.arrowEl.style, {
      left: a?.x != null ? `${a.x}px` : "",
      top: a?.y != null ? `${a.y}px` : "",
      [side === "bottom" ? "top" : "bottom"]: "-6px",
      [side === "bottom" ? "bottom" : "top"]: "",
    });
  }

  /** Swipe the sheet down by its handle to dismiss it. */
  private enableDrag(handle: HTMLElement, dismiss: () => void): void {
    let startY: number | null = null;
    let dy = 0;
    handle.addEventListener("pointerdown", (e) => {
      if (this.mode !== "sheet") return;
      startY = e.clientY;
      dy = 0;
      handle.setPointerCapture?.(e.pointerId);
      this.el.classList.add(`${C}--dragging`);
    });
    handle.addEventListener("pointermove", (e) => {
      if (startY === null) return;
      dy = Math.max(0, e.clientY - startY);
      this.el.style.transform = `translateY(${dy}px)`;
    });
    const end = () => {
      if (startY === null) return;
      startY = null;
      this.el.classList.remove(`${C}--dragging`);
      this.el.style.transform = "";
      if (dy > DISMISS_DRAG_PX) dismiss();
    };
    handle.addEventListener("pointerup", end);
    handle.addEventListener("pointercancel", end);
  }
}

function section(doc: Document, label: string, body: HTMLElement): HTMLElement {
  const wrap = el(doc, "section", `${C}__section`);
  const heading = el(doc, "p", `${C}__section-label`);
  heading.textContent = label;
  wrap.append(heading, body);
  return wrap;
}

function fillDebug(dl: HTMLDListElement, debug: AnnotationDebug | null): void {
  dl.replaceChildren();
  dl.hidden = debug === null;
  if (!debug) return;
  const rows: [string, string][] = [
    ["p_know", debug.p_know.toFixed(3)],
    ["salience", debug.salience.toFixed(2)],
    ["span_score", debug.span_score.toFixed(3)],
    ["domain", debug.domain],
    ["difficulty", debug.base_difficulty.toFixed(2)],
  ];
  for (const [k, v] of rows) {
    const dt = el(dl.ownerDocument, "dt", "");
    dt.textContent = k;
    const dd = el(dl.ownerDocument, "dd", "");
    dd.textContent = v;
    dl.append(dt, dd);
  }
}

function button(doc: Document, action: AnnotatorEventType, className: string): HTMLButtonElement {
  const b = el(doc, "button", className);
  b.type = "button";
  b.dataset.action = action;
  b.setAttribute("aria-pressed", "false");
  return b;
}

function thumbIcon(doc: Document): SVGSVGElement {
  const svg = doc.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 20 20");
  svg.setAttribute("width", "16");
  svg.setAttribute("height", "16");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  const path = doc.createElementNS(SVG_NS, "path");
  path.setAttribute(
    "d",
    "M6.5 8.5 9.4 3.2a1.6 1.6 0 0 1 3 .9l-.5 3.4h3.6a1.8 1.8 0 0 1 1.8 2.1l-1 5.4a2 2 0 0 1-2 1.6H6.5m0-8.1v8.1m0-8.1H4a1 1 0 0 0-1 1v6.1a1 1 0 0 0 1 1h2.5",
  );
  for (const [k, v] of Object.entries({
    fill: "none",
    stroke: "currentColor",
    "stroke-width": "1.5",
    "stroke-linecap": "round",
    "stroke-linejoin": "round",
  })) {
    path.setAttribute(k, v);
  }
  svg.append(path);
  return svg;
}

function el<K extends keyof HTMLElementTagNameMap>(
  doc: Document,
  tag: K,
  className: string,
): HTMLElementTagNameMap[K] {
  const node = doc.createElement(tag);
  if (className) node.className = className;
  return node;
}
