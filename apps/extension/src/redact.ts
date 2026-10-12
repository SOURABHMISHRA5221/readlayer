/**
 * Client redaction before anything leaves the browser (DESIGN §11.3). The same strict patterns
 * as the API's app/privacy/redact.py, checked against the same cases
 * (apps/api/tests/fixtures/redaction.json): emails, phones, Luhn-valid cards, Aadhaar and PAN
 * become `[REDACTED:type]`; news figures, dates and year ranges stay. Python's \w and \b are
 * Unicode-aware, so W below spells that out for JavaScript.
 */

const W = "[\\p{L}\\p{M}\\p{N}_]";

const EMAIL = new RegExp(`[\\p{L}\\p{M}\\p{N}_.+-]+@[\\p{L}\\p{M}\\p{N}_-]+(?:\\.[\\p{L}\\p{M}\\p{N}_-]+)+`, "gu");
const PAN = new RegExp(`(?<!${W})[A-Z]{5}[0-9]{4}[A-Z](?!${W})`, "gu");
// Cards: 13–19 digits grouped 4-4-4-x, or ungrouped with an issuer prefix; Luhn-checked.
const CARD = new RegExp(
  `(?<![\\p{L}\\p{M}\\p{N}_,.])(?:\\d{4}[ -]){3}\\d{1,7}(?![\\p{L}\\p{M}\\p{N}_,.])` +
    `|(?<![\\p{L}\\p{M}\\p{N}_,.])(?:4|5[1-5]|2[2-7]|3[47]|6|8[12])\\d{11,17}(?![\\p{L}\\p{M}\\p{N}_,.])`,
  "gu",
);
// Aadhaar: 4-4-4 with spaces, first digit 2–9.
const AADHAAR = /(?<![\d,.])(?<!\d )[2-9]\d{3} \d{4} \d{4}(?! ?\d)(?![,.]\d)/gu;
// Phones: +country code, an Indian mobile (0?[6-9]xxxx xxxxx), or a bracketed area code.
const PHONE = new RegExp(
  "\\+\\d{1,3}(?:[ -]?\\(?\\d{1,5}\\)?){2,5}" +
    "|(?<![\\d,.])0?[6-9]\\d{4}[ -]?\\d{5}(?!\\d|[,.]\\d)" +
    "|\\(0?\\d{2,4}\\)[ -]?\\d{3,4}[ -]?\\d{3,4}(?!\\d|[,.]\\d)",
  "gu",
);

const digits = (s: string) => s.replace(/\D/g, "");

function luhn(ds: string): boolean {
  let total = 0;
  let alt = false;
  for (let i = ds.length - 1; i >= 0; i--) {
    let d = Number(ds[i]);
    if (alt) {
      d *= 2;
      if (d > 9) d -= 9;
    }
    total += d;
    alt = !alt;
  }
  return total % 10 === 0;
}

const notCard = (m: string) => {
  const d = digits(m);
  return !(d.length >= 13 && d.length <= 19 && luhn(d));
};
const notPhone = (m: string) => {
  const n = digits(m).length;
  return n < 8 || n > 15;
};

type Step = [RegExp, string, ((m: string) => boolean)?];
const STEPS: readonly Step[] = [
  [EMAIL, "email"],
  [PAN, "pan"],
  [CARD, "card", notCard],
  [AADHAAR, "aadhaar"],
  [PHONE, "phone", notPhone],
];

export function redact(text: string): string {
  let out = text;
  for (const [pattern, kind, keep] of STEPS) {
    out = out.replace(pattern, (m) => (keep?.(m) ? m : `[REDACTED:${kind}]`));
  }
  return out;
}

/**
 * The page URL as sent: no fragment, no user info, every query value redacted (query strings
 * can carry emails or session tokens).
 */
export function redactUrl(href: string): string {
  const url = new URL(href);
  url.hash = "";
  url.username = "";
  url.password = "";
  const params = [...url.searchParams].map(([k, v]) => [k, redact(v)] as const);
  url.search = "";
  for (const [k, v] of params) url.searchParams.append(k, v);
  return url.toString();
}
