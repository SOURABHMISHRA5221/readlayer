/**
 * What public/theme-init.js chose for the first paint: "landing" (index.html's static hero, on "/"
 * with no signed-in hint) or "shell". While auth loads, the app keeps showing the same thing.
 */
export function bootsToLanding(): boolean {
  return document.documentElement.dataset.boot === "landing";
}
