/**
 * What Gloss reads, and how (one list for the hero's chips and the "What you can read" section,
 * decision 46c): articles and pasted links get notes; videos and podcasts are recommended in
 * the feed only. Never claim notes where there are none.
 */
export type FormatHow = "With notes" | "In your feed";

export const FORMATS: readonly { what: string; short: string; how: FormatHow }[] = [
  { what: "Articles", short: "Articles", how: "With notes" },
  { what: "Any link you paste", short: "Any link you paste", how: "With notes" },
  { what: "YouTube videos", short: "YouTube", how: "In your feed" },
  { what: "Podcasts", short: "Podcasts", how: "In your feed" },
];
