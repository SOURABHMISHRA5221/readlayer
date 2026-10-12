import { ANNOTATOR_CSS } from "@readlayer/annotator/src/styles";

import { call, run } from "./api";
import { WEB_BASE, WEB_ORIGINS } from "./config";
import type { Prepared } from "./content";
import type {
  ContentMessage,
  Density,
  ExternalMessage,
  PersonaKey,
  PopupMessage,
  ReadResult,
  Status,
} from "./messages";
import { REFUSAL_TEXT, refusalForUrl } from "./refuse";
import { claims, clear, load, save } from "./session";
import TOKENS_CSS from "./tokens.css?raw";

/**
 * Service worker (M8 §C2): the only part that holds the token or calls the API. Nothing runs on
 * a page until the reader clicks "Read this page" in the popup (activeTab grants that tab only).
 */

const fail = (reason: Exclude<ReadResult, { ok: true }>["reason"], message: string): ReadResult => ({
  ok: false,
  reason,
  message,
});

async function onboarded(): Promise<boolean | null> {
  const profile = await call<{ onboarding: { done: boolean } }>("GET", "/v1/me/profile");
  return profile.ok ? profile.data.onboarding.done : null;
}

export async function readTab(tabId: number): Promise<ReadResult> {
  const session = await load();
  if (!session) return fail("signed_out", "Connect Gloss from the web app first.");
  const tab = await chrome.tabs.get(tabId);
  // URL rules first: a mail, bank or private page never even gets our script.
  const byUrl = refusalForUrl(tab.url ?? "");
  if (byUrl) return fail("refused", REFUSAL_TEXT[byUrl]);
  if (!claims(session.idToken).anonymous && (await onboarded()) === false) {
    return fail("onboarding", "Finish setting up Gloss in the web app first.");
  }
  const target = { tabId };
  await chrome.scripting.executeScript({ target, files: ["content.js"] });
  const [first] = await chrome.scripting.executeScript({ target, func: () => globalThis.__readlayer!.prepare() });
  const prepared = first?.result as Prepared | undefined;
  if (!prepared) return fail("error", "Gloss couldn't read this page.");
  if ("mounted" in prepared) return { ok: true, already: true };
  if ("refused" in prepared) return fail("refused", REFUSAL_TEXT[prepared.refused]);
  if ("noArticle" in prepared) return fail("no_article", "Gloss couldn't find an article on this page.");
  // Only now, on an accepted page that isn't mounted yet: our CSS, then the overlay.
  await chrome.scripting.insertCSS({ target, css: ANNOTATOR_CSS + TOKENS_CSS });
  await chrome.scripting.executeScript({
    target,
    func: (webBase: string) => void globalThis.__readlayer!.start({ webBase }),
    args: [WEB_BASE],
  });
  return { ok: true, already: false };
}

async function status(): Promise<Status> {
  const session = await load();
  if (!session) {
    return { connected: false, demo: false, name: null, persona: null, density: "balanced", onboarded: null };
  }
  const { anonymous, name } = claims(session.idToken);
  return {
    connected: true,
    demo: anonymous,
    name,
    persona: anonymous ? session.persona ?? "newcomer" : null,
    density: session.density,
    onboarded: anonymous ? true : await onboarded(),
  };
}

async function settings(persona?: PersonaKey, density?: Density): Promise<Status> {
  const session = await load();
  if (session) {
    await save({ ...session, persona: persona ?? session.persona, density: density ?? session.density });
    if (density && !claims(session.idToken).anonymous) await call("PATCH", "/v1/me/settings", { density });
  }
  return status();
}

const fromPopup = (sender: chrome.runtime.MessageSender) =>
  sender.id === chrome.runtime.id && !sender.tab && (sender.url ?? "").startsWith(chrome.runtime.getURL("popup.html"));
const fromContent = (sender: chrome.runtime.MessageSender) =>
  sender.id === chrome.runtime.id && sender.tab?.id !== undefined;

chrome.runtime.onMessage.addListener((message: PopupMessage | ContentMessage, sender, reply) => {
  let work: Promise<unknown> | null = null;
  if (message.type === "api" && fromContent(sender)) work = run(message.call);
  else if (fromPopup(sender)) {
    if (message.type === "status") work = status();
    else if (message.type === "read") work = readTab(message.tabId).catch(() => fail("error", "Gloss couldn't read this page."));
    else if (message.type === "settings") work = settings(message.persona, message.density);
  }
  if (!work) return false;
  void work.then(reply);
  return true; // reply asynchronously
});

/** The web app's Connect page: only from our own origins (re-checked here, not just by the manifest). */
export async function onExternal(message: ExternalMessage, origin: string | undefined): Promise<unknown> {
  if (!origin || !WEB_ORIGINS.includes(origin)) return { ok: false, error: "origin" };
  if (message.type === "ping") return { ok: true, connected: (await load()) !== null };
  if (message.type === "disconnect") {
    await clear();
    return { ok: true };
  }
  if (message.type === "connect") {
    const valid = typeof message.idToken === "string" && typeof message.refreshToken === "string"
      && Number.isFinite(message.expiresAt);  // prettier-ignore
    if (!valid) return { ok: false, error: "invalid" };
    const previous = await load();
    await save({
      idToken: message.idToken,
      refreshToken: message.refreshToken,
      expiresAt: message.expiresAt,
      persona: message.persona ?? null,
      density: previous?.density ?? "balanced",
    });
    return { ok: true };
  }
  return { ok: false, error: "unknown" };
}

chrome.runtime.onMessageExternal.addListener((message: ExternalMessage, sender, reply) => {
  void onExternal(message, sender.origin).then(reply);
  return true;
});
