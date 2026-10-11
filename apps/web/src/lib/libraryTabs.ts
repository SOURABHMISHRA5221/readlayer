/** Library tabs (Design pass C5): the tab lives in the URL (`?tab=`), For you by default. */
export const TABS = [
  { id: "foryou", label: "For you" },
  { id: "topics", label: "Topics" },
  { id: "saved", label: "Saved" },
] as const;
export type Tab = (typeof TABS)[number]["id"];

export function parseTab(url: URL): Tab {
  if (url.pathname === "/for-you") return "foryou";
  const t = url.searchParams.get("tab");
  return t === "topics" || t === "saved" ? t : "foryou";
}

/** The `tab` query value for a tab: none for the default. */
export function tabParam(tab: Tab): string | null {
  return tab === "foryou" ? null : tab;
}
