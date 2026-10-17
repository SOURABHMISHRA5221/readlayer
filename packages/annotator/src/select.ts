/**
 * "Explain" on a selection (decision 70): a reader selects a word or phrase inside one paragraph
 * and gets a button (it follows the selection on scroll); pressing it hands the host the selection as offsets in the paragraph's
 * article text (our controls skipped, as anchors are), never the text itself.
 */

import { indexText, type TextIndex } from "./anchor";
import { isUi, UI_ATTR } from "./ui";

export interface SelectionAsk {
  paragraph_id: string;
  start: number;
  end: number;
}

export const SELECT_CLASS = "rl-select";
export const MIN_SELECTION = 2;
export const MAX_SELECTION = 120;
const SETTLE_MS = 300; // touch handles fire selectionchange only: wait for the drag to stop
const GAP_PX = 6;
const EDGE_PX = 8;

export interface SelectionWatch {
  hide(): void;
  destroy(): void;
}

export function watchSelection(
  root: HTMLElement,
  attr: string,
  onAsk: (ask: SelectionAsk) => void,
): SelectionWatch {
  const doc = root.ownerDocument;
  const view = doc.defaultView;
  let button: HTMLButtonElement | null = null;
  let current: SelectionAsk | null = null;
  let settle: ReturnType<typeof setTimeout> | undefined;

  function hide(): void {
    button?.remove();
    button = null;
    current = null;
  }

  function check(): void {
    const ask = readSelection(doc, root, attr);
    if (!ask) return hide();
    current = ask.ask;
    show(ask.paragraph, ask.range);
  }

  function show(paragraph: HTMLElement, range: Range): void {
    if (!button) {
      button = doc.createElement("button");
      button.type = "button";
      button.className = SELECT_CLASS;
      button.setAttribute(UI_ATTR, "");
      button.textContent = "Explain";
      button.setAttribute("aria-label", "Explain this");
      // Keep the selection while pressing; the click does the work.
      button.addEventListener("pointerdown", (e) => e.preventDefault());
      button.addEventListener("click", () => {
        const ask = current;
        hide();
        doc.getSelection()?.removeAllRanges();
        if (ask) onAsk(ask);
      });
    }
    // In the paragraph, so Tab reaches it right after the selected text; fixed, so no reflow.
    if (button.parentElement !== paragraph) paragraph.append(button);
    place(button, range);
  }

  function place(b: HTMLButtonElement, range: Range): void {
    const rects = typeof range.getClientRects === "function" ? range.getClientRects() : null;
    const last = rects && rects.length ? rects[rects.length - 1] : null;
    if (!last || !view) return;
    const width = b.offsetWidth || 80;
    const left = Math.min(Math.max(EDGE_PX, last.left), view.innerWidth - width - EDGE_PX);
    const below = last.bottom + GAP_PX;
    const top = below + 40 > view.innerHeight ? last.top - GAP_PX - (b.offsetHeight || 32) : below;
    b.style.left = `${Math.round(left)}px`;
    b.style.top = `${Math.round(top)}px`;
  }

  const onRelease = (): void => {
    clearTimeout(settle);
    check();
  };
  const onChange = (): void => {
    clearTimeout(settle);
    settle = setTimeout(check, SETTLE_MS);
  };
  const onKeyDown = (e: KeyboardEvent): void => {
    if (e.key === "Escape") hide();
  };
  // Scrolling keeps the selection: the button follows it (hidden if it scrolled out of the paragraph).
  let frame = 0;
  const onScroll = (): void => {
    if (!button || frame) return;
    frame = view?.requestAnimationFrame(() => {
      frame = 0;
      check();
    }) ?? 0;
  };

  doc.addEventListener("pointerup", onRelease);
  doc.addEventListener("keyup", onRelease);
  doc.addEventListener("selectionchange", onChange);
  doc.addEventListener("keydown", onKeyDown);
  view?.addEventListener("scroll", onScroll, { passive: true });

  return {
    hide,
    destroy() {
      clearTimeout(settle);
      if (frame) view?.cancelAnimationFrame(frame);
      hide();
      doc.removeEventListener("pointerup", onRelease);
      doc.removeEventListener("keyup", onRelease);
      doc.removeEventListener("selectionchange", onChange);
      doc.removeEventListener("keydown", onKeyDown);
      view?.removeEventListener("scroll", onScroll);
    },
  };
}

/** The selection as paragraph offsets, when it sits inside one paragraph of `root`. */
function readSelection(
  doc: Document,
  root: HTMLElement,
  attr: string,
): { ask: SelectionAsk; paragraph: HTMLElement; range: Range } | null {
  const sel = doc.getSelection();
  if (!sel || sel.isCollapsed || sel.rangeCount === 0) return null;
  const range = sel.getRangeAt(0);
  const common = range.commonAncestorContainer;
  const el = common.nodeType === 1 ? (common as Element) : common.parentElement;
  const paragraph = el?.closest<HTMLElement>(`[${attr}]`);
  if (!paragraph || !root.contains(paragraph) || isUi(el)) return null;
  const id = paragraph.getAttribute(attr);
  if (!id) return null;
  const idx = indexText(paragraph);
  let start = offsetIn(idx, range.startContainer, range.startOffset, doc);
  let end = offsetIn(idx, range.endContainer, range.endOffset, doc);
  while (start < end && /\s/.test(idx.text[start] ?? "")) start++;
  while (end > start && /\s/.test(idx.text[end - 1] ?? "")) end--;
  if (end - start < MIN_SELECTION || end - start > MAX_SELECTION) return null;
  return { ask: { paragraph_id: id, start, end }, paragraph, range };
}

/** A DOM boundary point as an offset in the indexed text (controls contribute nothing). */
function offsetIn(idx: TextIndex, container: Node, offset: number, doc: Document): number {
  const i = idx.nodes.indexOf(container as Text);
  if (i >= 0) return idx.starts[i]! + offset;
  // An element boundary or a point inside a control: the first indexed text at or after it.
  const point = doc.createRange();
  point.setStart(container, Math.min(offset, container.childNodes.length || offset));
  for (let k = 0; k < idx.nodes.length; k++) {
    const node = idx.nodes[k]!;
    if (point.comparePoint(node, 0) >= 0) return idx.starts[k]!;
  }
  return idx.text.length;
}
