/**
 * Client redaction before anything leaves the browser (DESIGN §11.3). The same strict patterns
 * as the API's app/privacy/redact.py, checked against the same cases
 * (apps/api/tests/fixtures/redaction.json): emails, phones, Luhn-valid cards, Aadhaar and PAN
 * become `[REDACTED:type]`; news figures, dates and year ranges stay. Python's \w and \b are
 * Unicode-aware, so W below spells that out for JavaScript.
 */

const W = "[\\p{L}\\p{M}\\p{N}_]";

// Emails: anything but spaces, quotes and brackets around one @, with a dotted domain (as Python).
const EMAIL_CHARS = "[^\\s@<>()\\[\\]{},;:\"'`]";
const LABEL = "[^\\s@<>()\\[\\]{},;:\"'`.]+";
// The last label starts with a letter, so "shares at 10@2.5" stays.
const EMAIL = new RegExp(`${EMAIL_CHARS}+@${LABEL}(?:\\.${LABEL})*\\.(?=\\p{L})${LABEL}`, "gu");
const PAN = new RegExp(`(?<!${W})[A-Z]{5}[0-9]{4}[A-Z](?!${W})`, "gu");
// Cards: 13–19 digits grouped 4-4-4-x, or ungrouped with an issuer prefix; Luhn-checked.
const CARD = new RegExp(
  `(?<![\\p{L}\\p{M}\\p{N}_,.])(?:\\p{Nd}{4}[ -]){3}\\p{Nd}{1,7}(?![\\p{L}\\p{M}\\p{N}_,.])` +
    `|(?<![\\p{L}\\p{M}\\p{N}_,.])(?:4|5[1-5]|2[2-7]|3[47]|6|8[12])\\p{Nd}{11,17}(?![\\p{L}\\p{M}\\p{N}_,.])`,
  "gu",
);
// Aadhaar: 4-4-4 with spaces, first digit 2–9.
const AADHAAR = /(?<![\p{Nd},.])(?<!\p{Nd} )[2-9]\p{Nd}{3} \p{Nd}{4} \p{Nd}{4}(?! ?\p{Nd})(?![,.]\p{Nd})/gu;
// Phones: +country code, an Indian mobile (0?[6-9]xxxx xxxxx), or a bracketed area code.
const PHONE = new RegExp(
  "\\+\\p{Nd}{1,3}(?:[ -]?\\(?\\p{Nd}{1,5}\\)?){2,5}" +
    "|(?<![\\p{Nd},.])0?[6-9]\\p{Nd}{4}[ -]?\\p{Nd}{5}(?!\\p{Nd}|[,.]\\p{Nd})" +
    "|\\(0?\\p{Nd}{2,4}\\)[ -]?\\p{Nd}{3,4}[ -]?\\p{Nd}{3,4}(?!\\p{Nd}|[,.]\\p{Nd})",
  "gu",
);

// Python's \d and int() take any Unicode digit (Devanagari, Bengali, …); so do these.
const digits = (s: string) => s.replace(/[^\p{Nd}]/gu, "");
const ZEROS = [0x30, 0x660, 0x6f0, 0x7c0, 0x966, 0x9e6, 0xa66, 0xae6, 0xb66, 0xbe6, 0xc66, 0xce6, 0xd66,
  0xde6, 0xe50, 0xed0, 0xf20, 0x1040, 0xff10];  // prettier-ignore
const digitValue = (ch: string) => {
  const cp = ch.codePointAt(0)!;
  const zero = ZEROS.find((z) => cp >= z && cp <= z + 9);
  return zero === undefined ? NaN : cp - zero;
};

function luhn(ds: string): boolean {
  let total = 0;
  let alt = false;
  const chars = [...ds];
  for (let i = chars.length - 1; i >= 0; i--) {
    let d = digitValue(chars[i]!);
    if (Number.isNaN(d)) return false;
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
  const n = [...d].length;
  return !(n >= 13 && n <= 19 && luhn(d));
};
const notPhone = (m: string) => {
  const n = [...digits(m)].length;
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
