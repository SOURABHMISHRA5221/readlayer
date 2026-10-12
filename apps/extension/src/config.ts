/**
 * Build-time settings (Vite env), all public: the committed .env.production (the live API's
 * URL and the web app's origins) or .env.emulator (local hosts, `vite build --mode emulator`).
 * The Firebase web API key isn't built in: the Connect page hands it over with the session.
 */

const env = import.meta.env as Record<string, string | undefined>;

const trim = (s: string | undefined) => (s ?? "").replace(/\/$/, "");

export const API_BASE = trim(env.VITE_API_BASE);
export const WEB_BASE = trim(env.VITE_WEB_BASE);
export const USE_EMULATORS = env.VITE_USE_EMULATORS === "1";
/** Firebase's token refresh endpoint (the Auth emulator serves the same path locally). */
export const SECURETOKEN_URL = USE_EMULATORS
  ? "http://127.0.0.1:9099/securetoken.googleapis.com/v1/token"
  : "https://securetoken.googleapis.com/v1/token";
/** Web origins allowed to connect (must match manifest externally_connectable). */
export const WEB_ORIGINS: readonly string[] = (env.VITE_WEB_ORIGINS ?? WEB_BASE)
  .split(",")
  .map((o) => trim(o.trim()))
  .filter(Boolean);
