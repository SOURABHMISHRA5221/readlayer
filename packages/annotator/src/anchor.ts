/**
 * Anchor resolution (DESIGN §9): find `exact` inside a scope, preferring the occurrence whose
 * surrounding text matches `prefix`/`suffix`; fall back to a whitespace-normalized search.
 * Works on character offsets into the scope's concatenated text nodes, so it never touches
 * the DOM; wrapping lives in mark.ts.
 */

import type { Anchor } from "./types";
import { UI_ATTR } from "./ui";

export interface TextIndex {
  text: string;
  nodes: Text[];
  /** starts[i] is the offset of nodes[i] within `text`. */
  starts: number[];
}

export interface TextRange {
  start: number;
  end: number;
}

/** The scope's text, in document order, leaving out the annotator's own controls. */
export function indexText(scope: Node): TextIndex {
  const doc = scope.ownerDocument ?? (scope as Document);
  const walker = doc.createTreeWalker(scope, 1 | 4 /* SHOW_ELEMENT | SHOW_TEXT */, {
    acceptNode: (node) =>
      node.nodeType === 3
        ? 1 /* FILTER_ACCEPT */
        : (node as Element).hasAttribute(UI_ATTR)
          ? 2 /* FILTER_REJECT: skip the whole control */
          : 3 /* FILTER_SKIP: look inside */,
  });
  const nodes: Text[] = [];
  const starts: number[] = [];
  let text = "";
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    if (n.nodeType !== 3) continue;
    const t = n as Text;
    nodes.push(t);
    starts.push(text.length);
    text += t.data;
  }
  return { text, nodes, starts };
}

/** Offsets of the anchor inside `text`, or null when it can't be found. */
export function resolveInText(text: string, anchor: Anchor, hint?: number): TextRange | null {
  if (!anchor.exact) return null;
  const exact = pick(text, anchor.exact, anchor.prefix, anchor.suffix, hint);
  if (exact !== null) return { start: exact, end: exact + anchor.exact.length };
  return resolveNormalized(text, anchor, hint);
}

function occurrences(haystack: string, needle: string): number[] {
  const found: number[] = [];
  for (let i = haystack.indexOf(needle); i !== -1; i = haystack.indexOf(needle, i + 1)) {
    found.push(i);
  }
  return found;
}

/** Best occurrence by prefix+suffix agreement, then closeness to the offset hint. */
function pick(
  text: string,
  exact: string,
  prefix: string,
  suffix: string,
  hint?: number,
): number | null {
  let best: number | null = null;
  let bestScore = -1;
  let bestDistance = Infinity;
  for (const at of occurrences(text, exact)) {
    const score =
      commonSuffix(text.slice(Math.max(0, at - prefix.length), at), prefix) +
      commonPrefix(text.slice(at + exact.length, at + exact.length + suffix.length), suffix);
    const distance = hint === undefined ? 0 : Math.abs(at - hint);
    if (score > bestScore || (score === bestScore && distance < bestDistance)) {
      best = at;
      bestScore = score;
      bestDistance = distance;
    }
  }
  return best;
}

function commonPrefix(a: string, b: string): number {
  let i = 0;
  while (i < a.length && i < b.length && a[i] === b[i]) i++;
  return i;
}

function commonSuffix(a: string, b: string): number {
  let i = 0;
  while (i < a.length && i < b.length && a[a.length - 1 - i] === b[b.length - 1 - i]) i++;
  return i;
}

interface Normalized {
  text: string;
  /** raw[i] is the raw offset of normalized character i. */
  raw: number[];
}

/** Collapse every whitespace run (incl. NBSP and newlines) to a single space. */
export function normalizeWhitespace(input: string): Normalized {
  let text = "";
  const raw: number[] = [];
  let inSpace = false;
  for (let i = 0; i < input.length; i++) {
    const ch = input[i] as string;
    if (/\s/.test(ch)) {
      if (!inSpace) {
        text += " ";
        raw.push(i);
      }
      inSpace = true;
    } else {
      text += ch;
      raw.push(i);
      inSpace = false;
    }
  }
  return { text, raw };
}

function resolveNormalized(text: string, anchor: Anchor, hint?: number): TextRange | null {
  const norm = normalizeWhitespace(text);
  const exact = normalizeWhitespace(anchor.exact).text.trim();
  if (!exact) return null;
  const at = pick(
    norm.text,
    exact,
    normalizeWhitespace(anchor.prefix).text,
    normalizeWhitespace(anchor.suffix).text,
    hint,
  );
  if (at === null) return null;
  const start = norm.raw[at] as number;
  const end = (norm.raw[at + exact.length - 1] as number) + 1;
  return { start, end };
}
