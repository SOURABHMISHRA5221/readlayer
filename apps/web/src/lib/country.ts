/** "Where do you read from?" (decision 50): which outlets count as local in For you. */
export const COUNTRIES = ["IN", "GB", "US", "other"] as const;
export type Country = (typeof COUNTRIES)[number];

export const COUNTRY_LABEL: Record<Country, string> = {
  IN: "India",
  GB: "United Kingdom",
  US: "United States",
  other: "Somewhere else",
};

/**
 * A suggestion from the browser's locale region (en-IN → India, fr-FR → Somewhere else). A
 * language without a region ("en") suggests nothing. Only a suggestion: it's stored when the
 * reader saves, never before.
 */
export function countryFromLocale(lang: string | undefined | null): Country | null {
  if (!lang) return null;
  let region: string | undefined;
  try {
    region = new Intl.Locale(lang).region;
  } catch {
    return null;
  }
  if (!region) return null;
  return (COUNTRIES as readonly string[]).includes(region) ? (region as Country) : "other";
}
