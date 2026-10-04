/**
 * Default look, injected once per document. Hosts theme it through --rl-* custom properties
 * on any ancestor (or :root); every value below is only a fallback.
 */

const STYLE_ID = "rl-annotator-styles";

const CSS = `
.rl-mark {
  text-decoration-line: underline;
  text-decoration-style: dotted;
  text-decoration-thickness: var(--rl-mark-thickness, 1.5px);
  text-decoration-color: var(--rl-mark, color-mix(in oklab, currentColor 40%, transparent));
  text-underline-offset: 0.3em;
  text-decoration-skip-ink: auto;
  border-radius: 2px;
  cursor: help;
  transition: background-color var(--rl-duration, 160ms) ease, text-decoration-color var(--rl-duration, 160ms) ease;
}
.rl-mark:hover,
.rl-mark[aria-expanded="true"] {
  background-color: var(--rl-mark-hover-bg, color-mix(in oklab, currentColor 7%, transparent));
  text-decoration-color: var(--rl-accent, currentColor);
}
.rl-mark:focus-visible {
  outline: 2px solid var(--rl-focus, var(--rl-accent, Highlight));
  outline-offset: 2px;
}
.rl-mark--known {
  text-decoration-color: var(--rl-mark-known, color-mix(in oklab, currentColor 15%, transparent));
}
.rl-card {
  position: absolute;
  z-index: 2147483000;
  box-sizing: border-box;
  width: min(22rem, calc(100vw - 32px));
  padding: 1rem 1.125rem 0.875rem;
  background: var(--rl-card-bg, #fffdf8);
  color: var(--rl-card-fg, #1d1b18);
  border: 1px solid var(--rl-card-border, rgba(29, 27, 24, 0.12));
  border-radius: var(--rl-radius, 10px);
  box-shadow: var(--rl-shadow, 0 1px 2px rgba(0,0,0,.06), 0 12px 32px -8px rgba(0,0,0,.18));
  font: 400 0.9375rem/1.5 var(--rl-font-ui, system-ui, sans-serif);
  text-align: left;
  animation: rl-card-in var(--rl-duration, 160ms) cubic-bezier(0.16, 1, 0.3, 1);
}
.rl-card[hidden] { display: none; }
.rl-card:focus { outline: none; }
.rl-card:focus-visible { outline: 2px solid var(--rl-focus, var(--rl-accent, Highlight)); outline-offset: 2px; }
.rl-card--sheet {
  position: fixed;
  inset: auto 0 0 0;
  width: auto;
  border-radius: var(--rl-radius, 10px) var(--rl-radius, 10px) 0 0;
  padding-bottom: calc(1rem + env(safe-area-inset-bottom, 0px));
  animation-name: rl-sheet-in;
}
.rl-card p { margin: 0; }
.rl-card__kicker {
  font-size: 0.6875rem;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--rl-muted, rgba(29, 27, 24, 0.6));
}
.rl-card__title {
  margin-top: 0.375rem !important;
  font: 600 1.0625rem/1.3 var(--rl-font-title, var(--rl-font-ui, system-ui, sans-serif));
}
.rl-card__def { margin-top: 0.375rem !important; }
.rl-card__prereq {
  margin-top: 0.625rem !important;
  font-size: 0.8125rem;
  color: var(--rl-muted, rgba(29, 27, 24, 0.6));
}
.rl-card__debug {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 0.125rem 0.75rem;
  margin: 0.75rem 0 0;
  padding: 0.5rem 0.625rem;
  border-radius: 6px;
  background: var(--rl-debug-bg, rgba(29, 27, 24, 0.05));
  font: 0.75rem/1.4 var(--rl-font-mono, ui-monospace, monospace);
}
.rl-card__debug[hidden] { display: none; }
.rl-card__debug dt { color: var(--rl-muted, rgba(29, 27, 24, 0.6)); }
.rl-card__debug dd { margin: 0; }
.rl-card__actions { display: flex; gap: 0.5rem; margin-top: 0.875rem; }
.rl-card__action {
  min-height: 2.25rem;
  padding: 0 0.875rem;
  border: 1px solid var(--rl-card-border, rgba(29, 27, 24, 0.16));
  border-radius: 999px;
  background: transparent;
  color: inherit;
  font: 500 0.8125rem/1 var(--rl-font-ui, system-ui, sans-serif);
  cursor: pointer;
  transition: background-color var(--rl-duration, 160ms) ease, border-color var(--rl-duration, 160ms) ease;
}
.rl-card__action:hover { background: var(--rl-action-hover-bg, rgba(29, 27, 24, 0.06)); }
.rl-card__action:active { transform: translateY(1px); }
.rl-card__action:focus-visible { outline: 2px solid var(--rl-focus, var(--rl-accent, Highlight)); outline-offset: 2px; }
.rl-card__action[aria-pressed="true"] {
  background: var(--rl-accent-soft, rgba(29, 27, 24, 0.08));
  border-color: var(--rl-accent, currentColor);
}
.rl-card__action[aria-pressed="true"]::before { content: "✓ "; }
@media (pointer: coarse) { .rl-card__action { min-height: 2.75rem; } }
@keyframes rl-card-in { from { opacity: 0; transform: translateY(-4px); } }
@keyframes rl-sheet-in { from { transform: translateY(100%); } }
@media (prefers-reduced-motion: reduce) {
  .rl-mark, .rl-card, .rl-card__action { transition: none; animation: none; }
}
`;

export function injectStyles(doc: Document): void {
  if (doc.getElementById(STYLE_ID)) return;
  const style = doc.createElement("style");
  style.id = STYLE_ID;
  style.textContent = CSS;
  doc.head.append(style);
}
