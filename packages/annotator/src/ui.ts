/**
 * Controls the annotator inserts into the article (paragraph markers, the "Know this?" chip)
 * carry UI_ATTR. They are never part of the article's text: anchor resolution skips them, a
 * copy leaves them out, and destroy removes them.
 */

export const UI_ATTR = "data-rl-ui";

export function isUi(node: Node | null): boolean {
  const el = node && (node.nodeType === 1 ? (node as Element) : node.parentElement);
  return !!el?.closest(`[${UI_ATTR}]`);
}

export function removeUi(root: HTMLElement): void {
  root.querySelectorAll(`[${UI_ATTR}]`).forEach((el) => el.remove());
}
