const WORDS_PER_MINUTE = 230;

const SOURCE_NAMES: Record<string, string> = {
  "Wikimedia Foundation, Inc.": "Wikipedia",
};

export function sourceName(site: string): string {
  return SOURCE_NAMES[site] ?? (site || "Unknown source");
}

/** Stable hue slot per source, so each publication keeps its badge colour. */
export function sourceTone(site: string): number {
  let h = 0;
  for (const ch of sourceName(site)) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return h % 5;
}

export function readingMinutes(words: number): number {
  return Math.max(1, Math.round(words / WORDS_PER_MINUTE));
}

export const formatCount = (n: number) => n.toLocaleString("en-IN");
