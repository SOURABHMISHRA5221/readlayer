import { FIREBASE_API_KEY, SECURETOKEN_URL } from "./config";
import type { Density, PersonaKey } from "./messages";

/**
 * The reader's session, from the web app's Connect page: Firebase ID token, refresh token and
 * expiry, plus the demo persona and density. Kept in chrome.storage.session only (cleared when
 * the browser closes, never written to disk) at its default TRUSTED_CONTEXTS access level, so
 * content scripts can't read it. Refreshed here through Firebase's securetoken endpoint, so no
 * ReadLayer tab needs to stay open (a deviation from DESIGN §11.1's "refresh via web app").
 * Tokens are never logged.
 */

export interface Session {
  idToken: string;
  refreshToken: string;
  expiresAt: number; // ms since epoch
  persona: PersonaKey | null;
  density: Density;
}

const KEY = "session";
const REFRESH_MARGIN_MS = 60_000;

export async function load(): Promise<Session | null> {
  const got = await chrome.storage.session.get(KEY);
  return (got[KEY] as Session | undefined) ?? null;
}

export async function save(session: Session): Promise<void> {
  await chrome.storage.session.set({ [KEY]: session });
}

export async function clear(): Promise<void> {
  await chrome.storage.session.remove(KEY);
}

export interface Claims {
  anonymous: boolean;
  name: string | null;
}

/** Display-only claims from the ID token (the API verifies the token itself). */
export function claims(idToken: string): Claims {
  try {
    const part = idToken.split(".")[1] ?? "";
    const json = JSON.parse(atob(part.replace(/-/g, "+").replace(/_/g, "/"))) as {
      name?: string;
      firebase?: { sign_in_provider?: string };
    };
    return { anonymous: json.firebase?.sign_in_provider === "anonymous", name: json.name ?? null };
  } catch {
    return { anonymous: false, name: null };
  }
}

/** A valid ID token, refreshed when it is within a minute of expiry (or `force`). */
export async function idToken(force = false): Promise<string | null> {
  const session = await load();
  if (!session) return null;
  if (!force && session.expiresAt - Date.now() > REFRESH_MARGIN_MS) return session.idToken;
  const res = await fetch(`${SECURETOKEN_URL}?key=${encodeURIComponent(FIREBASE_API_KEY)}`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ grant_type: "refresh_token", refresh_token: session.refreshToken }),
  });
  if (!res.ok) {
    // A revoked or expired refresh token: the reader connects again from the web app.
    if (res.status === 400 || res.status === 401) await clear();
    return null;
  }
  const data = (await res.json()) as { id_token: string; refresh_token: string; expires_in: string };
  await save({
    ...session,
    idToken: data.id_token,
    refreshToken: data.refresh_token,
    expiresAt: Date.now() + Number(data.expires_in) * 1000,
  });
  return data.id_token;
}
