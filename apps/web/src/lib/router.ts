import { useSyncExternalStore } from "react";

/** Two routes and URL-held state; a router dependency isn't worth it yet. */
export type Route =
  | { name: "library" }
  | { name: "reader"; id: string }
  | { name: "welcome" }
  | { name: "profile" }
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
  const href = useSyncExternalStore(subscribe, snapshot);
  return new URL(href, window.location.origin);
}

export function matchRoute(pathname: string): Route {
  if (pathname === "/") return { name: "library" };
  if (pathname === "/welcome") return { name: "welcome" };
  if (pathname === "/profile") return { name: "profile" };
  const reader = /^\/read\/([A-Za-z0-9_-]+)$/.exec(pathname);
  if (reader?.[1]) return { name: "reader", id: reader[1] };
  return { name: "missing" };
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
