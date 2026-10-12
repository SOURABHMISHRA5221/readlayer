/**
 * Talking to the Gloss extension (M8 §D). Its id is fixed by the public key in
 * apps/extension/manifest.base.json (apps/extension/test checks the two agree), and it accepts
 * messages only from the origins its manifest lists, re-checked in its worker.
 * `chrome.runtime.sendMessage` exists on this page only when an extension lists our origin.
 */

export const EXTENSION_ID = "lnfamfbeffepopbmedfenfmgljoacbmg";
const PING_TIMEOUT_MS = 1500;

interface RuntimeLike {
  sendMessage(id: string, message: unknown, reply: (response: unknown) => void): void;
  lastError?: { message?: string };
}

function runtime(): RuntimeLike | null {
  const rt = (globalThis as { chrome?: { runtime?: RuntimeLike } }).chrome?.runtime;
  return rt && typeof rt.sendMessage === "function" ? rt : null;
}

function send<T>(message: unknown, timeoutMs = PING_TIMEOUT_MS): Promise<T | null> {
  const rt = runtime();
  if (!rt) return Promise.resolve(null);
  return new Promise((resolve) => {
    const timer = setTimeout(() => resolve(null), timeoutMs);
    try {
      rt.sendMessage(EXTENSION_ID, message, (response) => {
        clearTimeout(timer);
        // Not installed (or disabled): Chrome reports it through lastError.
        resolve(rt.lastError ? null : ((response ?? null) as T | null));
      });
    } catch {
      clearTimeout(timer);
      resolve(null);
    }
  });
}

export type ExtensionState = "missing" | "disconnected" | "connected";

export async function extensionState(): Promise<ExtensionState> {
  const pong = await send<{ ok: boolean; connected?: boolean }>({ type: "ping" });
  if (!pong?.ok) return "missing";
  return pong.connected ? "connected" : "disconnected";
}

export interface ExtensionCredentials {
  idToken: string;
  refreshToken: string;
  expiresAt: number;
  persona: string | null;
}

export async function connectExtension(credentials: ExtensionCredentials): Promise<boolean> {
  const reply = await send<{ ok: boolean }>({ type: "connect", ...credentials }, 5000);
  return reply?.ok === true;
}

export async function disconnectExtension(): Promise<boolean> {
  const reply = await send<{ ok: boolean }>({ type: "disconnect" });
  return reply?.ok === true;
}
