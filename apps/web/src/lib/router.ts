import { useSyncExternalStore } from "react";

/** Two routes and URL-held state; a router dependency isn't worth it yet. */
export type Route =
  | { name: "library" }
  | { name: "reader"; id: string }
  | { name: "welcome" }
  | { name: "profile" }
  | { name: "feed" }
  | { name: "privacy" }
  | { name: "missing" };

const NAV_EVENT = "rl:navigate";

function subscribe(onChange: () => void): () => void {
  window.addEventListener("popstate", onChange);
  window.addEventListener(NAV_EVENT, onChange);
  return () => {
    window.removeEventListener("popstate", onChange);
    window.removeEventListener(NAV_EVENT, onChange);
  };
}

const snapshot = () => window.location.pathname + window.location.search;

export function useUrl(): URL {
  // The third argument: the landing hydrates index.html's static hero (main.tsx, decision 47).
  const href = useSyncExternalStore(subscribe, snapshot, snapshot);
  return new URL(href, window.location.origin);
}

export function matchRoute(pathname: string): Route {
  if (pathname === "/") return { name: "library" };
  if (pathname === "/welcome") return { name: "welcome" };
  if (pathname === "/profile") return { name: "profile" };
  if (pathname === "/for-you") return { name: "feed" };
  if (pathname === "/privacy") return { name: "privacy" };
  const reader = /^\/read\/([A-Za-z0-9_-]+)$/.exec(pathname);
  if (reader?.[1]) return { name: "reader", id: reader[1] };
  return { name: "missing" };
}

/** Where a signed-in reader must go first: consent and onboarding before anything else. */
export function onboardingRedirect(done: boolean | null, route: Route["name"]): string | null {
  return done === false && route !== "welcome" && route !== "privacy" ? "/welcome" : null;
}

const RETURN_KEY = "readlayer:return-to";
/** Routes worth coming back to after sign-in (a signed-out deep link shows the landing). */
const RETURNABLE: readonly Route["name"][] = ["reader", "profile", "feed"];

/**
 * A signed-out deep link: keep its path (never the query) in sessionStorage so the reader lands
 * there after sign-in or onboarding. Anything else clears it.
 */
export function rememberReturn(pathname: string): void {
  try {
    if (RETURNABLE.includes(matchRoute(pathname).name)) sessionStorage.setItem(RETURN_KEY, pathname);
    else sessionStorage.removeItem(RETURN_KEY);
  } catch {
    // Storage blocked: the reader lands on the feed instead.
  }
}

/** The remembered path, once (it is cleared), and only if it is still a returnable route. */
export function takeReturn(): string | null {
  try {
    const path = sessionStorage.getItem(RETURN_KEY);
    sessionStorage.removeItem(RETURN_KEY);
    return path && RETURNABLE.includes(matchRoute(path).name) ? path : null;
  } catch {
    return null;
  }
}

export function navigate(to: string, { replace = false } = {}): void {
  if (replace) window.history.replaceState(null, "", to);
  else window.history.pushState(null, "", to);
  window.dispatchEvent(new Event(NAV_EVENT));
}

/** Returns `path?params` with the given params set (empty or default values removed). */
export function withParams(url: URL, updates: Record<string, string | null>): string {
  const params = new URLSearchParams(url.search);
  for (const [k, v] of Object.entries(updates)) {
    if (v === null || v === "") params.delete(k);
    else params.set(k, v);
  }
  const qs = params.toString();
  return url.pathname + (qs ? `?${qs}` : "");
}
