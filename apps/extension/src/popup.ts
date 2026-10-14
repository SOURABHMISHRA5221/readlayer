import { PERSONAS, type Density, type PersonaKey, type ReadResult, type Status, type VideoResult } from "./messages";
import { VIDEO_HINT, youtubeWatchUrl } from "./youtube";

/** The toolbar popup (M8 §C4): who you are, "Read this page" (or "Open in Gloss" on a YouTube
 *  video, decision 62), persona (demo), density, links to the reader's own web address. */

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const send = <T>(message: unknown) => chrome.runtime.sendMessage(message) as Promise<T>;

function say(text: string, tone: "info" | "error" = "info"): void {
  const el = $("message");
  el.textContent = text;
  el.dataset.tone = tone;
}

function render(status: Status): void {
  $("connected").hidden = !status.connected || status.onboarded === false;
  $("setup").hidden = !(status.connected && status.onboarded === false);
  $("signed-out").hidden = status.connected;
  const persona = PERSONAS.find((p) => p.key === status.persona);
  $("who").textContent = !status.connected
    ? "Not connected"
    : status.demo
      ? `Demo · ${persona?.label ?? "Newcomer"}`
      : `Signed in${status.name ? ` as ${status.name}` : ""}`;
  $("persona-row").hidden = !status.demo;
  $<HTMLSelectElement>("persona").value = status.persona ?? "newcomer";
  $<HTMLSelectElement>("density").value = status.density;
  for (const [id, path] of [["profile", "/profile"], ["connect", "/connect"], ["setup-link", "/connect"]] as const) {
    $<HTMLAnchorElement>(id).href = `${status.web}${path}`;
  }
}

/** The active tab, if it is a YouTube video (activeTab: the popup was opened on this tab). */
async function activeTab(): Promise<{ id?: number; video: boolean }> {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return { id: tab?.id, video: youtubeWatchUrl(tab?.url) !== null };
}

async function openVideo(): Promise<void> {
  const button = $<HTMLButtonElement>("open-video");
  if (button.getAttribute("aria-disabled") === "true") return;
  const { id } = await activeTab();
  if (id === undefined) return say("No page to open here.", "error");
  button.setAttribute("aria-disabled", "true");
  say("Opening this video in Gloss…");
  const result = await send<VideoResult>({ type: "open-video", tabId: id });
  button.removeAttribute("aria-disabled");
  if (result.ok) return say("Opened in a new tab.");
  if (result.reason === "onboarding") render({ ...(await send<Status>({ type: "status" })), onboarded: false });
  say(result.message, result.reason === "onboarding" ? "info" : "error");
}

async function read(): Promise<void> {
  const button = $<HTMLButtonElement>("read");
  if (button.getAttribute("aria-disabled") === "true") return;
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (tab?.id === undefined) return say("No page to read here.", "error");
  button.setAttribute("aria-disabled", "true");
  say("Reading this page…");
  const result = await send<ReadResult>({ type: "read", tabId: tab.id });
  button.removeAttribute("aria-disabled");
  if (result.ok) {
    say(result.already ? "Notes are already on this page." : "Reading this page. Notes appear on it shortly; you can close this.");
    return;
  }
  if (result.reason === "onboarding") render({ ...(await send<Status>({ type: "status" })), onboarded: false });
  say(result.message, result.reason === "onboarding" ? "info" : "error");
}

function init(): void {
  const personas = $<HTMLSelectElement>("persona");
  for (const p of PERSONAS) personas.append(new Option(p.label, p.key));
  $("video-hint").textContent = VIDEO_HINT;
  $("read").addEventListener("click", () => void read());
  $("open-video").addEventListener("click", () => void openVideo());
  personas.addEventListener("change", () =>
    void send<Status>({ type: "settings", persona: personas.value as PersonaKey }).then(render),
  );
  const density = $<HTMLSelectElement>("density");
  density.addEventListener("change", () =>
    void send<Status>({ type: "settings", density: density.value as Density }).then(render),
  );
  void Promise.all([send<Status>({ type: "status" }), activeTab()]).then(([s, tab]) => {
    $("article-actions").hidden = tab.video;
    $("video-actions").hidden = !tab.video;
    render(s);
    if (s.connected && s.onboarded !== false) $(tab.video ? "open-video" : "read").focus();
  });
}

init();
