/**
 * Build-time settings (Vite env). Production: `make extension-config` writes .env.production.local
 * from the web app's public Firebase config and the API's URL. Emulator harness:
 * `vite build --mode emulator` reads the committed .env.emulator (local hosts, demo key).
 * Nothing here is secret: a Firebase web API key identifies the project, it grants nothing alone.
 */

const env = import.meta.env as Record<string, string | undefined>;

const trim = (s: string | undefined) => (s ?? "").replace(/\/$/, "");

export const API_BASE = trim(env.VITE_API_BASE);
export const WEB_BASE = trim(env.VITE_WEB_BASE);
export const FIREBASE_API_KEY = env.VITE_FIREBASE_API_KEY ?? "";
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
