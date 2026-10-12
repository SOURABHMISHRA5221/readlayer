import { Readability } from "@mozilla/readability";

/**
 * Article extraction (DESIGN §11.3): Readability on a clone of the page, so the live DOM is
 * never touched; only the title and paragraph text come out, never raw HTML, comments or form
 * fields. Paragraphs are the extracted article's block text (p, li, blockquote; headings
 * excluded), whitespace-normalised, at least MIN_PARAGRAPH_CHARS long like the API's own cleaner.
 */

export const MIN_PARAGRAPH_CHARS = 40; // app/ingest/extract.py MIN_PARAGRAPH_CHARS
export const MAX_PARAGRAPHS = 200; // POST /v1/content's limit
export const MAX_PARAGRAPH_CHARS = 5000;

export interface Extracted {
  title: string;
  paragraphs: string[];
}

export const normalize = (s: string): string => s.replace(/\s+/g, " ").trim();

const BLOCKS = "p, li, blockquote";

/** Block elements whose text is a paragraph: skip a block that contains another block. */
export function blockTexts(root: ParentNode): string[] {
  const out: string[] = [];
  for (const el of root.querySelectorAll(BLOCKS)) {
    if (el.querySelector(BLOCKS)) continue;
    const text = normalize(el.textContent ?? "");
    if (text.length >= MIN_PARAGRAPH_CHARS) out.push(text.slice(0, MAX_PARAGRAPH_CHARS));
  }
  return out.slice(0, MAX_PARAGRAPHS);
}

export function extractArticle(doc: Document): Extracted | null {
  const clone = doc.cloneNode(true) as Document;
  const article = new Readability(clone).parse();
  if (!article?.content) return null;
  // Parsed inert (DOMParser runs no scripts and loads nothing), never attached to the page.
  const parsed = new DOMParser().parseFromString(article.content, "text/html");
  const paragraphs = blockTexts(parsed.body);
  if (!paragraphs.length) return null;
  return { title: normalize(article.title ?? doc.title ?? "").slice(0, 500), paragraphs };
}
