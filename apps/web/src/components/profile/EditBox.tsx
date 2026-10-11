import { useEffect, useState } from "react";

import { ApiError } from "../../lib/api";
import type { PersonaKey } from "../../lib/personas";
import { profileApi, type EditPreview, type EditSummary } from "../../lib/profileApi";
import { interestLine, previewLines } from "../../lib/profileFormat";

const SETTING_NAMES: Record<string, string> = {
  thinks_in: "analogies",
  explanation_style: "explanation length",
  density: "notes",
  learning_paused: "pause",
};

interface Props {
  persona: PersonaKey | null;
  personaName: string | null;
  onChanged: () => void;
}

/**
 * "Describe yourself as a reader" (DESIGN §15.3): preview first, nothing changes until Apply,
 * every applied edit can be undone. For a demo reader it changes only this demo session's copy
 * of the persona, and "Reset" returns it to the original.
 */
export function EditBox({ persona, personaName, onChanged }: Props) {
  const [text, setText] = useState("");
  const [preview, setPreview] = useState<EditPreview | null>(null);
  const [edits, setEdits] = useState<EditSummary[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const loadEdits = () =>
    profileApi
      .edits(persona)
      .then((r) => setEdits(r.edits))
      .catch(() => undefined);

  useEffect(() => {
    setPreview(null);
    void loadEdits();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [persona]);

  const run = async (work: () => Promise<void>) => {
    setBusy(true);
    setMessage(null);
    try {
      await work();
    } catch (e) {
      setMessage(e instanceof ApiError && e.detail ? e.detail : "Something went wrong. Try again.");
    } finally {
      setBusy(false);
    }
  };

  const lines = preview ? previewLines(preview.preview) : [];
  const nothing = preview && lines.length === 0;

  return (
    <section className="editbox" aria-labelledby="editbox-title">
      <h2 id="editbox-title" className="profile__h2">
        Describe yourself as a reader
      </h2>
      {persona && (
        <p className="profile__note">
          Changes apply to {personaName ?? "this sample reader"} for this demo session only.
        </p>
      )}
      <form
        className="editbox__form"
        onSubmit={(e) => {
          e.preventDefault();
          if (text.trim()) void run(async () => setPreview(await profileApi.parseEdit(text.trim(), persona)));
        }}
      >
        <label htmlFor="editbox-text" className="visually-hidden">
          Describe yourself as a reader
        </label>
        <textarea
          id="editbox-text"
          rows={3}
          maxLength={500}
          value={text}
          placeholder="I'm a backend engineer, I know options trading well, keep explanations short"
          onChange={(e) => setText(e.target.value)}
        />
        <p className="editbox__notice">Your text is processed by AI to update your settings. It is not stored.</p>
        <div className="editbox__row">
          <button type="submit" className="btn btn--primary" disabled={busy || !text.trim()}>
            Preview changes
          </button>
        </div>
      </form>
      {message && (
        <p className="welcome__error" role="alert">
          {message}
        </p>
      )}
      {preview && (
        <div className="editbox__preview" role="region" aria-labelledby="editbox-preview-title">
          <h3 id="editbox-preview-title" className="editbox__h3">
            {nothing ? "Nothing to change" : "Here's what would change"}
          </h3>
          {nothing ? (
            <p className="profile__note">We didn't find anything to update in that. Try saying what you know, or how you like explanations.</p>
          ) : (
            <ul className="editbox__lines">
              {lines.map((l) => (
                <li key={l}>{l}</li>
              ))}
            </ul>
          )}
          {(preview.preview.known.length > 0 || preview.preview.unknown.length > 0) && (
            <details className="editbox__details">
              <summary>Which concepts</summary>
              <p>
                {[...preview.preview.known.map((c) => `${c.label} (known)`), ...preview.preview.unknown.map((c) => `${c.label} (new to you)`)].join(", ")}
              </p>
            </details>
          )}
          {preview.preview.note && <p className="profile__note">{preview.preview.note}</p>}
          {preview.preview.unresolved.length > 0 && (
            <p className="profile__note">Couldn't find: {preview.preview.unresolved.join(", ")}</p>
          )}
          <div className="editbox__row">
            <button type="button" className="btn" onClick={() => setPreview(null)} disabled={busy}>
              Discard
            </button>
            {!nothing && (
              <button
                type="button"
                className="btn btn--primary"
                disabled={busy}
                onClick={() =>
                  run(async () => {
                    await profileApi.applyEdit(preview.edit_id, persona);
                    setPreview(null);
                    setText("");
                    setMessage("Applied. Your next notes and explanations use it.");
                    await loadEdits();
                    onChanged();
                  })
                }
              >
                Apply
              </button>
            )}
          </div>
        </div>
      )}
      {edits.length > 0 && (
        <div className="editbox__history">
          <h3 className="editbox__h3">Your edits</h3>
          <ul>
            {edits.map((e) => (
              <li key={e.edit_id}>
                <span>
                  {e.applied_at ? new Date(e.applied_at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : ""} ·{" "}
                  {[
                    e.concepts ? `${e.concepts} concept${e.concepts > 1 ? "s" : ""}` : "",
                    ...e.domains.map((d) => `${d} level`),
                    ...e.settings.map((k) => SETTING_NAMES[k] ?? k),
                    ...(e.interests ?? []).map(interestLine),
                  ]
                    .filter(Boolean)
                    .join(", ")}
                </span>
                {e.status === "applied" ? (
                  <button
                    type="button"
                    className="btn btn--sm"
                    disabled={busy}
                    onClick={() =>
                      run(async () => {
                        await profileApi.undoEdit(e.edit_id, persona);
                        await loadEdits();
                        onChanged();
                      })
                    }
                  >
                    Undo
                  </button>
                ) : (
                  <span className="editbox__undone">Undone</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
      {persona && (
        <div className="editbox__row editbox__reset">
          <button
            type="button"
            className="btn btn--quiet"
            disabled={busy}
            onClick={() =>
              run(async () => {
                await profileApi.resetDemo(persona);
                setPreview(null);
                setEdits([]);
                setMessage(`${personaName ?? "The sample reader"} is back to the original.`);
                onChanged();
              })
            }
          >
            Reset {personaName ?? "persona"} to the original
          </button>
        </div>
      )}
    </section>
  );
}
