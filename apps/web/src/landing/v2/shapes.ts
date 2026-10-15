/**
 * The /v2 concept demo's text (docs/plans/landing-v2.md R4–R7): the landing's one Economic Times
 * sentence (`demoParagraph.json`, corpus paragraph p5, already public in this repo), split into its
 * clauses, and the "shapes" built from them. A shape never adds a word: every line is a clause or
 * runs of its own words joined by an ellipsis, in order (a test checks), and every shape keeps the
 * number, the hedge and the attribution.
 */
import { paragraph } from "../demoParagraph.json";

export type Length = "2min" | "5min" | "full";
export type Level = "simple" | "standard" | "expert";
export type Format = "read" | "listen" | "watch" | "scan";

export const SOURCE_TEXT: string = paragraph.text;
/** "¶5 s1": the corpus paragraph id's number (p5) and the sentence. */
export const TAG = `¶${paragraph.id.replace(/^p/, "")} s1`;

export interface Clause {
  id: string;
  /** The clause exactly as it appears in the sentence. */
  text: string;
  /** Shorter forms: runs of the clause's own words, joined by an ellipsis. */
  standard?: string;
  simple?: string;
}

export const CLAUSES: readonly Clause[] = [
  { id: "c1", text: "A 25 bps hike in October" },
  { id: "c2", text: "rather than December as previously forecast" },
  {
    id: "c3",
    text: "is possible amid higher energy prices, food inflation and wider price pressures",
    standard: "is possible amid higher energy prices, food inflation…",
    simple: "is possible amid higher energy prices…",
  },
  { id: "c4", text: "which strengthen the case for tighter policy" },
  { id: "c5", text: "according to Bank of America (BofA)." },
];

/** Never dropped or cut by any shape: the number, the hedge and the attribution. */
export const PROTECTED = ["25 bps", "October", "possible", "according to Bank of America (BofA)."] as const;

/** Which clauses each length keeps (always in the sentence's order). */
const BY_LENGTH: Readonly<Record<Length, readonly string[]>> = {
  full: ["c1", "c2", "c3", "c4", "c5"],
  "5min": ["c1", "c3", "c4", "c5"],
  "2min": ["c1", "c3", "c5"],
};

export interface Line {
  /** The source clause's id: the line's key, so a line keeps its element across shapes. */
  id: string;
  tag: string;
  text: string;
  /** Listen / Watch: when the line would start, at 150 words a minute (a mock). */
  at?: string;
}

const WORDS_PER_SECOND = 150 / 60;

const clock = (seconds: number) => {
  const s = Math.floor(seconds);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};

function textFor(c: Clause, level: Level, format: Format): string {
  const tier = format === "scan" ? "simple" : level;
  if (tier === "simple") return c.simple ?? c.text;
  if (tier === "standard") return c.standard ?? c.text;
  return c.text;
}

export function shape(length: Length, level: Level, format: Format): Line[] {
  const keep = new Set(BY_LENGTH[length]);
  let seconds = 0;
  return CLAUSES.filter((c) => keep.has(c.id)).map((c) => {
    const text = textFor(c, level, format);
    const line: Line = { id: c.id, tag: TAG, text };
    if (format === "listen" || format === "watch") line.at = clock(seconds);
    seconds += text.split(/\s+/).length / WORDS_PER_SECOND;
    return line;
  });
}

export const LENGTHS: readonly { key: Length; label: string }[] = [
  { key: "2min", label: "2 min" },
  { key: "5min", label: "5 min" },
  { key: "full", label: "Full" },
];
export const LEVELS: readonly { key: Level; label: string }[] = [
  { key: "simple", label: "Simple" },
  { key: "standard", label: "Standard" },
  { key: "expert", label: "Expert" },
];
export const FORMATS: readonly { key: Format; label: string }[] = [
  { key: "read", label: "Read" },
  { key: "listen", label: "Listen" },
  { key: "watch", label: "Watch" },
  { key: "scan", label: "Scan" },
];
