/**
 * The reader's left rail (Wide layout, decision 45): where each note sits in the article, how far
 * the reader is, and how long is left. Pure; the rail is components/reader/ReadingSpine.tsx.
 * Positions only: no article text is repeated.
 */
import type { CardAnnotation } from "@readlayer/annotator";

import { readingMinutes } from "./format";

export type SpineNote = Pick<CardAnnotation, "id" | "anchor" | "paragraph_id" | "level">;

export interface SpineTick {
  id: string;
  /** 0..1 down the article. */
  at: number;
  level: "new" | "refresher";
}

// Anchors are numbered over the paragraphs joined by a blank line (app/ingest/extract.py).
const SEPARATOR_CHARS = 2;

/** One tick per note, top to bottom. `anchor.start` is an article-level offset; without it, the
 *  note's paragraph and where its quote sits there. */
export function spineTicks(notes: readonly SpineNote[], paragraphs: readonly { id: string; text: string }[]): SpineTick[] {
  const starts = new Map<string, number>();
  const texts = new Map<string, string>();
  let total = 0;
  paragraphs.forEach((p, i) => {
    if (i) total += SEPARATOR_CHARS;
    starts.set(p.id, total);
    texts.set(p.id, p.text);
    total += p.text.length;
  });
  if (!total) return [];
  return notes
    .flatMap((note): SpineTick[] => {
      const start = note.anchor.start ?? inParagraph(note, starts, texts);
      if (start === undefined) return [];
      return [{ id: note.id, at: Math.min(1, Math.max(0, start / total)), level: note.level === "refresher" ? "refresher" : "new" }];
    })
    .sort((a, b) => a.at - b.at);
}

function inParagraph(note: SpineNote, starts: ReadonlyMap<string, number>, texts: ReadonlyMap<string, string>): number | undefined {
  const start = starts.get(note.paragraph_id);
  if (start === undefined) return undefined;
  return start + Math.max(0, (texts.get(note.paragraph_id) ?? "").indexOf(note.anchor.exact));
}

/** The share of the article above the middle of the screen: the same scale the ticks are on.
 *  At the page's end it is 1, since a short article's end may never reach mid-screen. */
export function placeInArticle(top: number, height: number, viewport: number, atPageEnd: boolean): number {
  if (atPageEnd) return 1;
  if (height <= 0) return 0;
  return Math.min(1, Math.max(0, (viewport / 2 - top) / height));
}

/** Whole minutes still to read, from the byline's reading time; 0 at the end. */
export function minutesLeft(wordCount: number, place: number): number {
  return place >= 1 ? 0 : Math.ceil(readingMinutes(wordCount) * (1 - place));
}
