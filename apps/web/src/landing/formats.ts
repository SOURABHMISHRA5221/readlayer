/**
 * The hero's "Read with Gloss" chips (main bundle). A projection of the full list in
 * `formatsFull.ts` (landing chunk only, decision 61 R1); a vitest keeps the two in step.
 */
export const CHIPS: readonly { label: string; notes: boolean }[] = [
  { label: "Articles", notes: true },
  { label: "Any link", notes: true },
  { label: "Short videos", notes: true },
  { label: "Podcasts", notes: true },
  { label: "Chrome extension", notes: true },
];
