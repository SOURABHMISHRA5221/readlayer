import { describe, expect, it } from "vitest";

import { refusal, refusalForDocument, refusalForUrl } from "../src/refuse";

describe("refusalForUrl", () => {
  it.each([
    "https://mail.google.com/mail/u/0/#inbox",
    "https://outlook.live.com/mail/0/",
    "https://mail.yahoo.com/d/folders/1",
    "https://mail.proton.me/u/0/inbox",
    "https://netbanking.hdfcbank.com/netbanking/",
    "https://www.icicibank.com/login",
    "https://retail.onlinesbi.sbi/retail/login.htm",
    "https://www.paypal.com/signin",
    "https://accounts.google.com/v3/signin/identifier?continue=https://mail.google.com/",
    "https://login.microsoftonline.com/common/oauth2/authorize",
    "https://login.live.com/",
    "http://intranet/wiki",
    "http://wiki.corp/home",
    "http://printer.local/",
    "http://localhost:8080/",
    "http://192.168.1.10/admin",
    "http://10.0.0.5/",
    "http://[::1]/",
    "chrome://settings",
    "file:///Users/me/notes.html",
    "chrome-extension://abc/popup.html",
  ])("refuses %s", (url) => {
    expect(refusalForUrl(url)).toBe("private_page");
  });
  it.each([
    "https://www.theguardian.com/business/2026/oct/08/bond-yields",
    "https://www.bbc.co.uk/news/business-12345",
    "https://economictimes.indiatimes.com/markets/stocks/news/abc/articleshow/1.cms",
    "https://en.wikipedia.org/wiki/Yield_curve",
  ])("reads %s", (url) => {
    expect(refusalForUrl(url)).toBeNull();
  });
});

describe("refusalForDocument", () => {
  const page = (html: string) => new DOMParser().parseFromString(html, "text/html");
  it("refuses a page with a password field", () => {
    expect(refusalForDocument(page('<form><input type="Password"></form>'))).toBe("sensitive_fields");
  });
  it("refuses a page with a card field", () => {
    expect(refusalForDocument(page('<input autocomplete="cc-number">'))).toBe("sensitive_fields");
  });
  it("reads a page with only a newsletter email box", () => {
    expect(refusalForDocument(page('<p>Story</p><input type="email">'))).toBeNull();
  });
  it("checks the URL first", () => {
    expect(refusal(page("<p>x</p>"), "https://mail.google.com/")).toBe("private_page");
  });
});
