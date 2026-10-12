import { WEB_BASE } from "./config";
import { PERSONAS, type Density, type PersonaKey, type ReadResult, type Status } from "./messages";

/** The toolbar popup (M8 §C4): who you are, "Read this page", persona (demo), density, links. */

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
  for (const [id, path] of [["profile", "/profile"], ["connect", "/connect"], ["setup-link", "/connect"]] as const) {
    $<HTMLAnchorElement>(id).href = `${WEB_BASE}${path}`;
  }
  $("read").addEventListener("click", () => void read());
  personas.addEventListener("change", () =>
    void send<Status>({ type: "settings", persona: personas.value as PersonaKey }).then(render),
  );
  const density = $<HTMLSelectElement>("density");
  density.addEventListener("change", () =>
    void send<Status>({ type: "settings", density: density.value as Density }).then(render),
  );
  void send<Status>({ type: "status" }).then((s) => {
    render(s);
    if (s.connected && s.onboarded !== false) $("read").focus();
  });
}

init();
