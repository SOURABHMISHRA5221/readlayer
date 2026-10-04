/**
 * The span card: one shared non-modal dialog, filled with textContent only (annotation data
 * is never parsed as HTML).
 */

import type { AnnotationDebug, AnnotatorEventType, CardAnnotation } from "./types";

export const CARD_LABEL = "Explanation — not the author's words";
const CARD_CLASS = "rl-card";
const GAP_PX = 8;
const GUTTER_PX = 16;
export const SHEET_QUERY = "(max-width: 639px)";

let cardCount = 0;

export interface CardHandlers {
  onAction: (type: AnnotatorEventType) => void;
}

export class Card {
  readonly el: HTMLDivElement;
  private readonly title: HTMLParagraphElement;
  private readonly definition: HTMLParagraphElement;
  private readonly prereqs: HTMLParagraphElement;
  private readonly debug: HTMLDListElement;
  private readonly buttons: HTMLButtonElement[];

  constructor(doc: Document, handlers: CardHandlers) {
    const id = `rl-card-${++cardCount}`;
    this.el = el(doc, "div", CARD_CLASS);
    this.el.id = id;
    this.el.hidden = true;
    this.el.tabIndex = -1;
    this.el.setAttribute("role", "dialog");
    this.el.setAttribute("aria-labelledby", `${id}-title`);
    this.el.setAttribute("aria-describedby", `${id}-def`);

    const kicker = el(doc, "p", `${CARD_CLASS}__kicker`);
    kicker.textContent = CARD_LABEL;
    this.title = el(doc, "p", `${CARD_CLASS}__title`);
    this.title.id = `${id}-title`;
    this.definition = el(doc, "p", `${CARD_CLASS}__def`);
    this.definition.id = `${id}-def`;
    this.prereqs = el(doc, "p", `${CARD_CLASS}__prereq`);
    this.debug = el(doc, "dl", `${CARD_CLASS}__debug`);

    const actions = el(doc, "div", `${CARD_CLASS}__actions`);
    this.buttons = (
      [
        ["knew_this", "Knew this"],
        ["explain_helpful", "Helpful"],
      ] as const
    ).map(([type, text]) => {
      const b = el(doc, "button", `${CARD_CLASS}__action`);
      b.type = "button";
      b.textContent = text;
      b.dataset.action = type;
      b.setAttribute("aria-pressed", "false");
      b.addEventListener("click", () => {
        b.setAttribute("aria-pressed", "true");
        handlers.onAction(type);
      });
      return b;
    });
    actions.append(...this.buttons);
    this.el.append(kicker, this.title, this.definition, this.prereqs, this.debug, actions);
    doc.body.append(this.el);
  }

  get id(): string {
    return this.el.id;
  }

  get isOpen(): boolean {
    return !this.el.hidden;
  }

  fill(a: CardAnnotation, pressed: ReadonlySet<AnnotatorEventType>): void {
    this.title.textContent = a.label;
    this.definition.textContent = a.definition;
    const prereqs = a.prerequisites.slice(0, 3);
    this.prereqs.hidden = prereqs.length === 0;
    this.prereqs.textContent = prereqs.length ? `Before this: ${prereqs.join(" · ")}` : "";
    fillDebug(this.debug, a.debug ?? null);
    for (const b of this.buttons) {
      const type = b.dataset.action as AnnotatorEventType;
      b.setAttribute("aria-pressed", String(pressed.has(type)));
    }
  }

  show(anchor: HTMLElement): void {
    const view = this.el.ownerDocument.defaultView;
    const sheet = view?.matchMedia?.(SHEET_QUERY).matches ?? false;
    this.el.classList.toggle(`${CARD_CLASS}--sheet`, sheet);
    this.el.hidden = false;
    if (!sheet && view) this.position(anchor, view);
  }

  hide(): void {
    this.el.hidden = true;
  }

  contains(node: Node | null): boolean {
    return !!node && this.el.contains(node);
  }

  destroy(): void {
    this.el.remove();
  }

  private position(anchor: HTMLElement, view: Window): void {
    const rect = anchor.getBoundingClientRect();
    const { offsetWidth: w, offsetHeight: h } = this.el;
    const below = rect.bottom + GAP_PX + h <= view.innerHeight || rect.top < h + GAP_PX;
    const top = below ? rect.bottom + GAP_PX : rect.top - GAP_PX - h;
    const maxLeft = view.innerWidth - w - GUTTER_PX;
    const left = Math.max(GUTTER_PX, Math.min(rect.left, maxLeft));
    this.el.style.top = `${top + view.scrollY}px`;
    this.el.style.left = `${left + view.scrollX}px`;
    this.el.dataset.placement = below ? "below" : "above";
  }
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

function el<K extends keyof HTMLElementTagNameMap>(
  doc: Document,
  tag: K,
  className: string,
): HTMLElementTagNameMap[K] {
  const node = doc.createElement(tag);
  if (className) node.className = className;
  return node;
}
