import { useId, useState, type FormEvent } from "react";

import { api, ApiError, errorKind } from "../lib/api";
import { personaParam, type PersonaKey } from "../lib/personas";
import { navigate, withParams } from "../lib/router";
import { Margo } from "./Margo";

type State = { status: "idle" } | { status: "busy" } | { status: "error"; message: string };

/** Paste any article URL: it opens in the reader at once (two-phase "Open here", M7.5 §B).
 *  Sends the URL and nothing else; the page stays visible only to readers who bring it in. */
type Props = { persona: PersonaKey | null; hideLabel?: boolean; id?: string };

export function ReadAnyLink({ persona, hideLabel = false, id }: Props) {
  const [url, setUrl] = useState("");
  const [state, setState] = useState<State>({ status: "idle" });
  const hintId = useId();

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const value = url.trim();
    if (!value) return;
    setState({ status: "busy" });
    try {
      const { content_id } = await api.openWeb(value);
      navigate(withParams(new URL(`/read/${content_id}`, window.location.origin), { persona: personaParam(persona) }));
      window.scrollTo(0, 0);
    } catch (error) {
      const message =
        error instanceof ApiError && error.detail
          ? error.detail
          : errorKind(error) === "offline"
            ? "Couldn't reach Gloss. Check your connection and try again."
            : "That link couldn't be opened here. Try another article.";
      setState({ status: "error", message });
    }
  };

  return (
    <form className="anylink" id={id} onSubmit={submit} aria-describedby={hintId}>
      <label className={hideLabel ? "visually-hidden" : "anylink__label"} htmlFor={`${hintId}-url`}>
        Read any link
      </label>
      <div className="anylink__row">
        <input
          id={`${hintId}-url`}
          className="anylink__input"
          type="url"
          inputMode="url"
          autoComplete="off"
          spellCheck={false}
          required
          placeholder="Paste an article link"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          disabled={state.status === "busy"}
        />
        <button className="btn anylink__go" type="submit" disabled={state.status === "busy" || !url.trim()}>
          {state.status === "busy" ? "Opening…" : "Read"}
        </button>
      </div>
      <p id={hintId} className={`anylink__hint${state.status === "error" ? " anylink__hint--error" : ""}`} aria-live="polite">
        {state.status === "error" && <Margo mood="oops" size={28} />}
        <span>{state.status === "error" ? state.message : "Opens here with notes for you. The original stays untouched."}</span>
      </p>
    </form>
  );
}
