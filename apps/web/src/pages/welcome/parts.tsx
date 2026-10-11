import { useRef, useState, type ReactNode } from "react";

import { Margo, type MargoMood } from "../../components/Margo";
import { Wordmark } from "../../components/Wordmark";
import { api } from "../../lib/api";
import { signOutUser } from "../../lib/auth";

export function Shell({ screen, children }: { screen: 1 | 2; children: ReactNode }) {
  return (
    <div className="welcome">
      <header className="welcome__bar">
        <Wordmark />
        <p className="welcome__step">
          <span className="visually-hidden">Step </span>
          {screen} of 2
        </p>
      </header>
      <main className="welcome__main">{children}</main>
    </div>
  );
}

/** Margo speaks one short line beside the screen's heading. */
export function MargoSays({ mood, children }: { mood: MargoMood; children: ReactNode }) {
  return (
    <div className="welcome__margo">
      <Margo mood={mood} size={56} />
      <p className="welcome__says" aria-live="polite">
        {children}
      </p>
    </div>
  );
}

interface ChipGroupProps<K extends string> {
  legend: string;
  hint?: string;
  options: { key: K; label: string }[];
  selected: K[];
  onToggle: (key: K) => void;
  multiple?: boolean;
}

/** One row of tappable chips with a visible legend: radios, or checkboxes when `multiple`. */
export function ChipGroup<K extends string>({ legend, hint, options, selected, onToggle, multiple = false }: ChipGroupProps<K>) {
  return (
    <fieldset className="chips">
      <legend className="chips__legend">
        {legend}
        {hint && <span className="chips__hint"> {hint}</span>}
      </legend>
      <div className="chips__row">
        {options.map((o) => {
          const on = selected.includes(o.key);
          return (
            <label key={o.key} className="chip" data-on={on}>
              <input type={multiple ? "checkbox" : "radio"} name={legend} checked={on} onChange={() => onToggle(o.key)} />
              <span>{o.label}</span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}

/** Export and delete work before consent too (the API keeps them open), so leaving is easy. */
export function DataLinks() {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const deleteButton = useRef<HTMLButtonElement>(null);
  const exportData = async () => {
    setBusy(true);
    try {
      const blob = await api.exportMe();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "readlayer-export.json";
      a.click();
      URL.revokeObjectURL(a.href);
    } catch {
      setMessage("The export didn't download. Try again.");
    } finally {
      setBusy(false);
    }
  };
  const deleteAll = async () => {
    setBusy(true);
    try {
      await api.deleteMe();
      await signOutUser();
    } catch {
      setMessage("We couldn't delete your account. Try again.");
      setBusy(false);
    }
  };
  return (
    <div className="welcome__data">
      <button type="button" className="btn btn--link" onClick={() => void exportData()} disabled={busy}>
        Export my data
      </button>
      {!confirming ? (
        <button type="button" ref={deleteButton} className="btn btn--link btn--link-danger" onClick={() => setConfirming(true)} disabled={busy}>
          Delete my account
        </button>
      ) : (
        <span
          className="welcome__confirm"
          role="group"
          aria-label="Confirm delete"
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              setConfirming(false);
              requestAnimationFrame(() => deleteButton.current?.focus());
            }
          }}
        >
          <span>Delete your account and everything with it?</span>
          <button type="button" className="btn" autoFocus onClick={() => setConfirming(false)} disabled={busy}>
            Cancel
          </button>
          <button type="button" className="btn btn--danger" onClick={() => void deleteAll()} disabled={busy}>
            Delete
          </button>
        </span>
      )}
      {message && (
        <p className="welcome__error" role="alert">
          {message}
        </p>
      )}
    </div>
  );
}
