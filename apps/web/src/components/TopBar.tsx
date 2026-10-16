import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";

import { useIsDemo } from "../lib/auth";
import { DEFAULT_PERSONA, readerPersona, type PersonaKey } from "../lib/personas";
import { navigate, withParams } from "../lib/router";
import { AccountMenu } from "./AccountMenu";
import { Close, LinkIcon, Search } from "./Icons";
import { PersonaPicker } from "./PersonaPicker";
import { ReadAnyLink } from "./ReadAnyLink";
import { ThemeToggle } from "./ThemeToggle";
import { Wordmark } from "./Wordmark";

type SearchProps = { value: string; onChange: (v: string) => void };

/**
 * Gloss top bar (Design pass C4): logo, search, "Open any link", the demo persona chip, theme
 * and account. On the library the search filters in place; elsewhere it opens the Topics tab.
 * "Open any link" focuses the sidebar field when the page has one, else opens a small dialog.
 */
export function TopBar({ url, search, children }: { url: URL; search?: SearchProps; children?: ReactNode }) {
  const persona = readerPersona(url, useIsDemo());
  const [draft, setDraft] = useState("");
  const dialog = useRef<HTMLDialogElement>(null);

  const submitSearch = (e: FormEvent) => {
    e.preventDefault();
    if (search) return;
    navigate(withParams(new URL("/", window.location.origin), { tab: "topics", q: draft.trim() || null, persona: url.searchParams.get("persona") }));
  };
  const openAnyLink = () => {
    const field = document.getElementById("anylink-side")?.querySelector<HTMLInputElement>("input");
    if (field && field.offsetParent !== null) {
      field.scrollIntoView({ block: "center" });
      field.focus();
      return;
    }
    dialog.current?.showModal();
  };
  const setPersona = (k: PersonaKey) =>
    navigate(withParams(url, { persona: k === DEFAULT_PERSONA ? null : k }), { replace: true });

  useEffect(() => {
    const d = dialog.current;
    const close = () => d?.close();
    window.addEventListener("rl:navigate", close);
    return () => window.removeEventListener("rl:navigate", close);
  }, []);

  return (
    <header className="topbar">
      <div className="topbar__inner">
        <Wordmark size="lg" />
        <form className="topbar__search" role="search" onSubmit={submitSearch}>
          <label className="visually-hidden" htmlFor="topbar-q">
            Search the library
          </label>
          <Search className="topbar__search-icon" />
          <input
            id="topbar-q"
            type="search"
            placeholder="Search"
            autoComplete="off"
            spellCheck={false}
            value={search ? search.value : draft}
            onChange={(e) => (search ? search.onChange(e.target.value) : setDraft(e.target.value))}
          />
        </form>
        <div className="topbar__spacer" />
        {children}
        <button type="button" className="topbar__link" onClick={openAnyLink}>
          <LinkIcon />
          <span className="topbar__link-text">Open any link</span>
        </button>
        {persona && <PersonaPicker value={persona} onChange={setPersona} />}
        <ThemeToggle />
        <AccountMenu />
      </div>
      <dialog ref={dialog} className="sheet" aria-labelledby="anylink-dialog-title">
        <div className="sheet__head">
          <h2 id="anylink-dialog-title" className="sheet__title">
            Open any link
          </h2>
          <button type="button" className="icon-btn" aria-label="Close" onClick={() => dialog.current?.close()}>
            <Close />
          </button>
        </div>
        <ReadAnyLink persona={persona} hideLabel />
      </dialog>
    </header>
  );
}
