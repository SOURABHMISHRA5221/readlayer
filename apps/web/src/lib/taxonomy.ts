/** The fixed domain taxonomy (decision 33). Mirrors apps/api/app/graph/taxonomy.py, in the same
 *  order; an API test parses this file and fails if the two lists differ. */
export const DOMAINS = [
  "economics",
  "finance",
  "business",
  "policy",
  "politics",
  "law",
  "technology",
  "science",
  "health",
  "environment",
  "sports",
  "culture",
  "education",
  "society",
] as const;

export type Domain = (typeof DOMAINS)[number];

/** The graph's original core (the first four), shown when a reader has rated nothing. */
export const BUSINESS_DOMAINS: readonly Domain[] = DOMAINS.slice(0, 4);
