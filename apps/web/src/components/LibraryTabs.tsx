import { personaParam, type PersonaKey } from "../lib/personas";
import { withParams } from "../lib/router";

/** "Library · For you" (M7.5 §D.1). Plain links, so each tab is a real, shareable page. */
export function LibraryTabs({ current, persona }: { current: "library" | "feed"; persona: PersonaKey | null }) {
  const href = (path: string) =>
    withParams(new URL(path, window.location.origin), { persona: personaParam(persona) });
  return (
    <nav className="libtabs" aria-label="Library views">
      <a className="libtabs__tab" href={href("/")} aria-current={current === "library" ? "page" : undefined}>
        Library
      </a>
      <a className="libtabs__tab" href={href("/for-you")} aria-current={current === "feed" ? "page" : undefined}>
        For you
      </a>
    </nav>
  );
}
