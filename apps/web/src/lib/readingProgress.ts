/** Share of the page read, for the thin line at the top: full once the page's end is 60% of a
 *  screen away, so the line completes as the last paragraph comes into view. */
export function readingProgress(top: number, height: number, viewport: number): number {
  const span = height - viewport * 0.6;
  return span <= 0 ? 1 : Math.min(1, Math.max(0, -top / span));
}
