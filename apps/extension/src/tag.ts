import { normalize } from "./extract";
import { redact } from "./redact";

/**
 * Mounting on the live page (DESIGN §9): each paragraph the server stored is matched to the live
 * element that holds it and tagged `data-rl-paragraph="pN"`; the article text is never changed.
 *
 * Server paragraphs are our own text after its cleaner and redactor, so the match key is the
 * live element's text, redacted and whitespace-normalised: equal means the same paragraph. When
 * the server answered with the fetch path's doc (its own extraction of the URL, not our text),
 * an unmatched paragraph falls back to the live element whose text starts with the paragraph's
 * first PREFIX_CHARS. The deepest matching element wins (a <p>, not the <div> around it).
 */

export const PARAGRAPH_ATTR = "data-rl-paragraph";
const PREFIX_CHARS = 80;
const MAX_ELEMENT_CHARS = 6000;
const SKIP = "script, style, noscript, template, [data-rl-ui], nav, footer, form";

export interface ServerParagraph {
  id: string;
  text: string;
}

export interface Tagged {
  /** Common ancestor of the tagged elements: the annotator's root. */
  root: HTMLElement;
  elements: Map<string, HTMLElement>;
  unmatched: string[];
}

interface Candidate {
  el: HTMLElement;
  key: string; // redacted + normalised
  plain: string; // normalised only
  depth: number;
}

function depth(el: Element): number {
  let d = 0;
  for (let n: Element | null = el; n; n = n.parentElement) d++;
  return d;
}

function candidates(doc: Document): Candidate[] {
  const out: Candidate[] = [];
  for (const el of doc.body.querySelectorAll<HTMLElement>("p, li, blockquote, div, dd, figcaption, td, span")) {
    if (el.closest(SKIP)) continue;
    const raw = el.textContent ?? "";
    if (raw.length > MAX_ELEMENT_CHARS) continue;
    const plain = normalize(raw);
    if (plain.length < 20) continue;
    out.push({ el, key: normalize(redact(plain)), plain, depth: depth(el) });
  }
  return out.sort((a, b) => b.depth - a.depth); // deepest first
}

function commonAncestor(elements: HTMLElement[]): HTMLElement {
  let node: HTMLElement | null = elements[0] ?? null;
  while (node && !elements.every((e) => node!.contains(e))) node = node.parentElement;
  return node ?? elements[0]!.ownerDocument.body;
}

export function tagParagraphs(doc: Document, paragraphs: readonly ServerParagraph[]): Tagged | null {
  const pool = candidates(doc);
  const used = new Set<HTMLElement>();
  const elements = new Map<string, HTMLElement>();
  const unmatched: string[] = [];
  const take = (p: ServerParagraph, pick: (c: Candidate) => boolean) => {
    // Never an element inside or around one already tagged for another paragraph.
    const hit = pool.find((c) => pick(c) && ![...used].some((u) => u.contains(c.el) || c.el.contains(u)));
    if (hit) {
      used.add(hit.el);
      elements.set(p.id, hit.el);
    }
    return Boolean(hit);
  };
  for (const p of paragraphs) {
    const text = normalize(p.text);
    if (take(p, (c) => c.key === text)) continue;
    const head = text.slice(0, PREFIX_CHARS);
    if (take(p, (c) => c.plain === text || (head.length >= 40 && c.plain.startsWith(head)))) continue;
    unmatched.push(p.id);
  }
  if (!elements.size) return null;
  for (const [id, el] of elements) el.setAttribute(PARAGRAPH_ATTR, id);
  return { root: commonAncestor([...elements.values()]), elements, unmatched };
}
