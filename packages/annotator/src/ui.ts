/**
 * Controls the annotator inserts into the article (paragraph markers, the "Know this?" chip)
 * carry UI_ATTR. They are never part of the article's text: anchor resolution skips them, a
 * copy leaves them out, and destroy removes them.
 */

export const UI_ATTR = "data-rl-ui";
/** UI_ATTR's value on a control the host page owns (a transcript's time button): anchors and
 * copy skip it like any UI, but destroy leaves it in place, since the host renders it. */
export const HOST_UI = "host";

export function isUi(node: Node | null): boolean {
  const el = node && (node.nodeType === 1 ? (node as Element) : node.parentElement);
  return !!el?.closest(`[${UI_ATTR}]`);
}

export function removeUi(root: HTMLElement): void {
  root.querySelectorAll(`[${UI_ATTR}]:not([${UI_ATTR}="${HOST_UI}"])`).forEach((el) => el.remove());
}
