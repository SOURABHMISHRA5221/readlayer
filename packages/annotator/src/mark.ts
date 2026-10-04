/**
 * Wraps resolved text ranges in marks without changing a single character of the text:
 * text nodes are split at the boundaries and the inner pieces moved into `<span>`s.
 */

import { indexText, type TextRange } from "./anchor";

export const MARK_CLASS = "rl-mark";
const ID_ATTR = "data-rl-id";

/**
 * Wraps root-level offsets [start, end) and returns the mark segments, first one first.
 * Returns [] when the range overlaps an existing mark (the earlier, higher-ranked one wins).
 */
export function wrapRange(root: HTMLElement, range: TextRange, id: string): HTMLElement[] {
  const index = indexText(root);
  const pieces: { node: Text; from: number; to: number }[] = [];
  index.nodes.forEach((node, i) => {
    const nodeStart = index.starts[i] as number;
    const nodeEnd = nodeStart + node.data.length;
    if (nodeEnd <= range.start || nodeStart >= range.end) return;
    pieces.push({
      node,
      from: Math.max(range.start, nodeStart) - nodeStart,
      to: Math.min(range.end, nodeEnd) - nodeStart,
    });
  });
  if (!pieces.length || pieces.some((p) => p.node.parentElement?.closest(`.${MARK_CLASS}`))) {
    return [];
  }
  return pieces
    .filter((p) => p.to > p.from)
    .map(({ node, from, to }) => {
      const middle = from > 0 ? node.splitText(from) : node;
      if (to - from < middle.data.length) middle.splitText(to - from);
      const mark = root.ownerDocument.createElement("span");
      mark.className = MARK_CLASS;
      mark.setAttribute(ID_ATTR, id);
      middle.replaceWith(mark);
      mark.append(middle);
      return mark;
    });
}

/** Removes the given marks (or every mark under root), restoring the original text nodes. */
export function unwrap(root: HTMLElement, marks?: readonly Element[]): void {
  const parents = new Set<Node>();
  for (const mark of marks ?? Array.from(root.querySelectorAll(`.${MARK_CLASS}`))) {
    const parent = mark.parentNode;
    if (!parent) continue;
    parents.add(parent);
    mark.replaceWith(...Array.from(mark.childNodes));
  }
  parents.forEach((p) => p.normalize());
}

export function markId(el: Element): string | null {
  return el.closest(`.${MARK_CLASS}`)?.getAttribute(ID_ATTR) ?? null;
}
