/**
 * Pages ReadLayer never reads (DESIGN §11.3), checked on click before anything else: mail, banking
 * and private-network URLs, non-web schemes, and any page with a password or card field. A
 * refused page gets nothing from us (no CSS, no attributes); the popup says why.
 */

export type Refusal = "private_page" | "sensitive_fields";

export const REFUSAL_TEXT: Record<Refusal, string> = {
  private_page: "Gloss doesn't read mail, banking or private pages.",
  sensitive_fields: "This page has a password or card field, so Gloss won't read it.",
};

const MAIL_HOSTS = ["mail.google.com", "outlook.live.com", "outlook.office.com", "outlook.office365.com",
  "mail.yahoo.com", "proton.me", "mail.proton.me", "mail.zoho.com", "mail.zoho.in", "icloud.com"];  // prettier-ignore
const BANK_HOSTS = ["onlinesbi.sbi", "sbi.co.in", "kotak.com", "paypal.com", "chase.com",
  "wellsfargo.com", "citi.com", "online.citi.com", "americanexpress.com", "barclays.co.uk",
  "hsbc.com", "hsbc.co.in", "hsbc.co.uk", "revolut.com", "wise.com", "paytm.com",
  "phonepe.com", "razorpay.com", "lloydsbank.com", "natwest.com", "santander.co.uk"];  // prettier-ignore
const BANK_WORD = /bank|netbanking|ibanking/;
const PRIVATE_SUFFIXES = [".local", ".internal", ".corp", ".lan", ".home", ".home.arpa", ".intranet",
  ".localhost"];  // prettier-ignore

const onHost = (host: string, domains: readonly string[]) =>
  domains.some((d) => host === d || host.endsWith(`.${d}`));

function privateIp(host: string): boolean {
  const h = host.replace(/^\[|\]$/g, "");
  const v4 = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(h);
  if (v4) {
    const [a, b] = [Number(v4[1]), Number(v4[2])];
    return a === 10 || a === 127 || a === 0 || (a === 169 && b === 254) || (a === 172 && b >= 16 && b <= 31)
      || (a === 192 && b === 168) || (a === 100 && b >= 64 && b <= 127);  // prettier-ignore
  }
  if (h.includes(":")) return h === "::1" || /^f[cd]/i.test(h) || /^fe[89ab]/i.test(h);
  return false;
}

/** URL rules: anything but a public http(s) news-like page is refused. */
export function refusalForUrl(href: string): Refusal | null {
  let url: URL;
  try {
    url = new URL(href);
  } catch {
    return "private_page";
  }
  if (url.protocol !== "https:" && url.protocol !== "http:") return "private_page";
  const host = url.hostname.toLowerCase().replace(/\.$/, "");
  if (!host.includes(".") || host === "localhost") return "private_page"; // single-label: intranet
  if (privateIp(host) || PRIVATE_SUFFIXES.some((s) => host.endsWith(s))) return "private_page";
  if (onHost(host, MAIL_HOSTS) || onHost(host, BANK_HOSTS) || BANK_WORD.test(host)) return "private_page";
  return null;
}

/** Field rules, on the live page before anything is read. */
export function refusalForDocument(doc: Document): Refusal | null {
  if (doc.querySelector('input[type="password" i]')) return "sensitive_fields";
  if (doc.querySelector('[autocomplete^="cc-" i]')) return "sensitive_fields";
  return null;
}

export function refusal(doc: Document, href: string): Refusal | null {
  return refusalForUrl(href) ?? refusalForDocument(doc);
}
