import { useCallback, useSyncExternalStore } from "react";

export type Theme = "light" | "dark";

const STORAGE_KEY = "readlayer:theme";
const THEME_EVENT = "rl:theme";
const DARK_QUERY = "(prefers-color-scheme: dark)";

function stored(): Theme | null {
  try {
    const value = window.localStorage.getItem(STORAGE_KEY);
    return value === "light" || value === "dark" ? value : null;
  } catch {
    return null;
  }
}

function current(): Theme {
  return stored() ?? (window.matchMedia(DARK_QUERY).matches ? "dark" : "light");
}

function subscribe(onChange: () => void): () => void {
  const media = window.matchMedia(DARK_QUERY);
  media.addEventListener("change", onChange);
  window.addEventListener(THEME_EVENT, onChange);
  return () => {
    media.removeEventListener("change", onChange);
    window.removeEventListener(THEME_EVENT, onChange);
  };
}

/** Light/dark from the OS until the reader picks one; the pick is remembered per browser. */
export function useTheme(): [Theme, () => void] {
  const theme = useSyncExternalStore(subscribe, current);
  const toggle = useCallback(() => {
    const next: Theme = current() === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Private mode or blocked storage: the choice lasts for this page only.
    }
    window.dispatchEvent(new Event(THEME_EVENT));
  }, []);
  return [theme, toggle];
}
