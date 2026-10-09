/**
 * Default look, injected once per document. Hosts theme it through --rl-* custom properties
 * on any ancestor (or :root); every value below is only a fallback.
 */

const STYLE_ID = "rl-annotator-styles";

const CSS = `
.rl-mark {
  color: inherit;
  text-decoration-line: underline;
  text-decoration-style: dotted;
  text-decoration-thickness: 1.5px;
  text-underline-offset: 4px;
  text-decoration-skip-ink: none;
  text-decoration-color: color-mix(in srgb, var(--rl-accent, #1f5f5b) 45%, transparent);
  border-radius: 3px;
  box-decoration-break: clone;
  -webkit-box-decoration-break: clone;
  cursor: pointer;
  transition:
    text-decoration-color var(--rl-duration, 180ms) var(--rl-ease, ease-out),
    background-color var(--rl-duration, 180ms) var(--rl-ease, ease-out);
}
.rl-mark:hover,
.rl-mark:focus-visible,
.rl-mark--linked,
.rl-mark[aria-expanded="true"] {
  text-decoration-style: solid;
  text-decoration-color: var(--rl-accent, #1f5f5b);
  background-color: var(--rl-accent-wash, #e6f0ee);
}
.rl-mark:focus-visible {
  outline: 2px solid var(--rl-focus, var(--rl-accent, #1f5f5b));
  outline-offset: 2px;
}
.rl-mark--known:not(:hover):not(:focus-visible):not([aria-expanded="true"]) {
  text-decoration-color: color-mix(in srgb, var(--rl-muted, #6b675f) 35%, transparent);
}
.rl-mark--entering {
  animation: rl-mark-in 560ms var(--rl-ease, ease-out) both;
}
.rl-mark--leaving {
  text-decoration-color: transparent !important;
  background-color: transparent !important;
  cursor: auto;
}
@keyframes rl-mark-in {
  0% { text-decoration-color: transparent; background-color: transparent; }
  35% { background-color: var(--rl-accent-wash, #e6f0ee); }
  100% { background-color: transparent; }
}

.rl-card {
  position: fixed;
  z-index: 2147483000;
  top: 0;
  left: 0;
  box-sizing: border-box;
  width: min(360px, calc(100vw - 24px));
  padding: 16px 18px 12px;
  background: var(--rl-surface, #fffdf9);
  color: var(--rl-ink, #1c1b19);
  border: 1px solid var(--rl-hairline, #e7e1d6);
  border-radius: var(--rl-radius, 10px);
  box-shadow: var(--rl-shadow, 0 1px 2px rgba(28,27,25,.06), 0 16px 40px -12px rgba(28,27,25,.22));
  font: 400 14px/1.5 var(--rl-font-ui, system-ui, sans-serif);
  text-align: left;
  display: flex;
  flex-direction: column;
  -webkit-font-smoothing: antialiased;
  animation: rl-card-in var(--rl-duration, 180ms) var(--rl-ease, ease-out);
}
.rl-card[hidden], .rl-scrim[hidden] { display: none; }
.rl-card__body {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  margin: 0 -18px;
  padding: 0 18px;
}
.rl-card__body--more {
  -webkit-mask-image: linear-gradient(to bottom, #000 calc(100% - 36px), transparent);
  mask-image: linear-gradient(to bottom, #000 calc(100% - 36px), transparent);
}
.rl-card__footer { flex: none; }
.rl-card:focus { outline: none; }
.rl-card p { margin: 0; }
.rl-card__arrow {
  position: absolute;
  width: 12px;
  height: 12px;
  background: inherit;
  border: 1px solid var(--rl-hairline, #e7e1d6);
  transform: rotate(45deg);
}
.rl-card[data-placement^="bottom"] .rl-card__arrow { border-right: 0; border-bottom: 0; }
.rl-card[data-placement^="top"] .rl-card__arrow { border-left: 0; border-top: 0; }
.rl-card[data-placement="right"] .rl-card__arrow { border-top: 0; border-right: 0; }
.rl-card__handle { display: none; }
.rl-card__domain {
  font: 600 11px/1 var(--rl-font-ui, system-ui, sans-serif);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  font-variant: all-small-caps;
  font-size: 13px;
  color: var(--rl-accent, #1f5f5b);
}
.rl-card__domain[hidden] { display: none; }
.rl-card__title {
  margin-top: 6px !important;
  font: 500 20px/1.25 var(--rl-font-read, Georgia, serif);
  letter-spacing: -0.01em;
  text-wrap: balance;
}

.rl-card__explain[hidden], .rl-card__frame[hidden], .rl-btn[hidden] { display: none; }
.rl-card__explain { display: grid; gap: 12px; margin-top: 12px; }
.rl-card__section-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.rl-card__section-label {
  font: 600 11px/1.2 var(--rl-font-ui, system-ui, sans-serif);
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--rl-muted, #6b675f);
}
.rl-card__text { margin-top: 4px !important; text-wrap: pretty; animation: rl-text-in 260ms var(--rl-ease, ease-out); }
/* Background: our words, recessed on a tinted panel; the only place an analogy may appear. */
.rl-card__bg {
  padding: 10px 12px 11px;
  border-radius: calc(var(--rl-radius, 10px) - 2px);
  background: color-mix(in srgb, var(--rl-accent-wash, #e6f0ee) 70%, transparent);
}
.rl-card__bg .rl-card__text { font-size: 0.93em; color: var(--rl-ink-soft, var(--rl-ink, #1c1b19)); }
.rl-card__frame {
  flex: none;
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--rl-surface, #fffdf9);
  color: var(--rl-accent, #1f5f5b);
  font: 500 11px/1.4 var(--rl-font-ui, system-ui, sans-serif);
}
/* What the author is saying: the primary block, ruled in the accent that marks the text. */
.rl-card__says { padding-left: 12px; border-left: 2px solid var(--rl-accent, #1f5f5b); }
.rl-card__says .rl-card__section-label { color: var(--rl-accent, #1f5f5b); }
.rl-card__says .rl-card__text { color: var(--rl-ink, #1c1b19); }
.rl-card__explain[data-state="loading"] .rl-card__says .rl-card__text,
.rl-card__explain[data-state="ready"] .rl-card__skeleton { display: none; }
.rl-card__section[hidden] { display: none; }
.rl-card__skeleton { display: grid; gap: 7px; padding: 6px 0 2px; }
.rl-card__skeleton-line {
  display: block;
  height: 9px;
  border-radius: 999px;
  background: linear-gradient(90deg, var(--rl-hairline, #e7e1d6) 0%, var(--rl-surface, #fffdf9) 50%, var(--rl-hairline, #e7e1d6) 100%) 0 0 / 200% 100%;
  animation: rl-shimmer 1.4s ease-in-out infinite;
}
.rl-card__skeleton-line:nth-child(2) { width: 88%; }
.rl-card__skeleton-line:nth-child(3) { width: 62%; }
.rl-card__says .rl-card__skeleton-line { width: 94%; }
.rl-card__loading-note {
  font: 400 12px/1.45 var(--rl-font-ui, system-ui, sans-serif);
  color: var(--rl-muted, #6b675f);
}
.rl-card__status {
  position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%);
  white-space: nowrap;
}
.rl-card__status--visible {
  position: static; width: auto; height: auto; overflow: visible; clip-path: none;
  white-space: normal;
  margin-top: 12px !important;
  padding: 9px 12px;
  border: 1px dashed var(--rl-hairline, #e7e1d6);
  border-radius: calc(var(--rl-radius, 10px) - 2px);
  font: 400 13px/1.45 var(--rl-font-ui, system-ui, sans-serif);
  color: var(--rl-muted, #6b675f);
}
.rl-card__prereqs { margin-top: 12px; }
.rl-card__prereqs[hidden] { display: none; }
.rl-card__prereq-label {
  font: 500 12px/1 var(--rl-font-ui, system-ui, sans-serif);
  color: var(--rl-muted, #6b675f);
}
.rl-card__chips { display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0 0; padding: 0; list-style: none; }
.rl-chip {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 0 10px;
  border: 1px solid var(--rl-hairline, #e7e1d6);
  border-radius: 999px;
  font: 500 12px/1 var(--rl-font-ui, system-ui, sans-serif);
  color: var(--rl-ink, #1c1b19);
  background: var(--rl-paper, transparent);
}
.rl-card__debug {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 2px 12px;
  margin: 12px 0 0;
  padding: 8px 10px;
  border-radius: 6px;
  background: var(--rl-accent-wash, #e6f0ee);
  font: 12px/1.4 var(--rl-font-mono, ui-monospace, monospace);
  font-variant-numeric: tabular-nums;
}
.rl-card__debug[hidden] { display: none; }
.rl-card__debug dt { color: var(--rl-muted, #6b675f); }
.rl-card__debug dd { margin: 0; }
.rl-card__footer {
  margin-top: 14px;
  padding-top: 10px;
  border-top: 1px solid var(--rl-hairline, #e7e1d6);
}
.rl-card__actions { display: flex; align-items: center; gap: 4px; }
.rl-card__note {
  margin-top: 8px !important;
  font: 400 11px/1.3 var(--rl-font-ui, system-ui, sans-serif);
  color: var(--rl-muted, #6b675f);
}
.rl-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 32px;
  border: 1px solid transparent;
  border-radius: 999px;
  background: transparent;
  color: var(--rl-ink, #1c1b19);
  font: 500 13px/1 var(--rl-font-ui, system-ui, sans-serif);
  cursor: pointer;
  transition: background-color 150ms var(--rl-ease, ease-out), color 150ms var(--rl-ease, ease-out), border-color 150ms var(--rl-ease, ease-out);
}
.rl-btn--ghost { padding: 0 12px; margin-left: -12px; }
.rl-btn--quiet { margin-left: 0; color: var(--rl-muted, #6b675f); font-weight: 400; }
.rl-btn:disabled { opacity: 0.45; cursor: default; }
.rl-btn:disabled[aria-pressed="true"] { opacity: 1; }
.rl-btn--icon { width: 32px; padding: 0; margin-left: auto; color: var(--rl-muted, #6b675f); }
.rl-btn:hover { background: var(--rl-accent-wash, #e6f0ee); color: var(--rl-accent, #1f5f5b); }
.rl-btn:active { transform: translateY(1px); }
.rl-btn:focus-visible { outline: 2px solid var(--rl-focus, var(--rl-accent, #1f5f5b)); outline-offset: 1px; }
.rl-btn[aria-pressed="true"] { color: var(--rl-accent, #1f5f5b); background: var(--rl-accent-wash, #e6f0ee); }
.rl-btn--ghost[aria-pressed="true"]::before { content: "✓"; }
.rl-btn--icon[aria-pressed="true"] path { fill: currentColor; fill-opacity: 0.2; }

.rl-scrim {
  position: fixed;
  inset: 0;
  z-index: 2147482999;
  background: var(--rl-scrim, rgba(20, 20, 18, 0.32));
  animation: rl-fade-in 200ms var(--rl-ease, ease-out);
}
.rl-card[data-mode="sheet"] {
  inset: auto 0 0 0;
  width: auto;
  max-height: 80vh;
  padding: 8px 20px calc(16px + env(safe-area-inset-bottom, 0px));
  border-width: 1px 0 0;
  border-radius: 16px 16px 0 0;
  font-size: 15px;
  animation: rl-sheet-in 220ms var(--rl-ease, ease-out);
  transition: transform 200ms var(--rl-ease, ease-out);
}
.rl-card[data-mode="sheet"].rl-card--dragging { transition: none; }
.rl-card[data-mode="sheet"] .rl-card__arrow { display: none; }
.rl-card[data-mode="sheet"] .rl-card__handle {
  display: block;
  width: 100%;
  height: 24px;
  margin-bottom: 4px;
  cursor: grab;
  touch-action: none;
  background: linear-gradient(var(--rl-hairline, #e7e1d6), var(--rl-hairline, #e7e1d6)) center / 40px 4px no-repeat;
  border-radius: 999px;
}
.rl-card[data-mode="sheet"] .rl-card__body { margin: 0 -20px; padding: 0 20px; }
.rl-card[data-mode="sheet"] .rl-btn { min-height: 44px; }
.rl-card[data-mode="sheet"] .rl-btn--icon { width: 44px; }
@keyframes rl-card-in { from { opacity: 0; transform: translateY(4px); } }
@keyframes rl-sheet-in { from { transform: translateY(100%); } }
@keyframes rl-fade-in { from { opacity: 0; } }
@keyframes rl-shimmer { to { background-position: -200% 0; } }
@keyframes rl-text-in { from { opacity: 0; } }
@media (prefers-reduced-motion: reduce) {
  .rl-mark, .rl-card, .rl-scrim, .rl-btn, .rl-card__skeleton-line, .rl-card__text {
    transition: none; animation: none !important;
  }
}
`;

export function injectStyles(doc: Document): void {
  if (doc.getElementById(STYLE_ID)) return;
  const style = doc.createElement("style");
  style.id = STYLE_ID;
  style.textContent = CSS;
  doc.head.append(style);
}
