import { useEffect, useId, useRef, useState } from "react";

import { api } from "../lib/api";
import { signOutUser, useSession } from "../lib/auth";
import { navigate } from "../lib/router";

type Step = { kind: "menu" } | { kind: "confirm-delete" } | { kind: "busy"; label: string } | { kind: "error"; message: string };

function initials(name: string | null): string {
  const parts = (name ?? "").trim().split(/\s+/).filter(Boolean);
  return parts.length ? parts.slice(0, 2).map((p) => p[0]!.toUpperCase()).join("") : "Me";
}

async function downloadExport(): Promise<void> {
  const blob = await api.exportMe();
  const href = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = href;
  a.download = "readlayer-export.json";
  a.click();
  setTimeout(() => URL.revokeObjectURL(href), 1000);
}

/**
 * Who is reading, and their data controls (DESIGN §11.4): Export / Delete / Sign out for a
 * Google account; End demo for an anonymous demo session (which deletes its data, so demo
 * accounts don't pile up). A disclosure, not a menu role: plain buttons in Tab order.
 */
export function AccountMenu() {
  const session = useSession();
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState<Step>({ kind: "menu" });
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const panelId = useId();

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onDown);
    panelRef.current?.querySelector<HTMLElement>("button")?.focus();
    return () => document.removeEventListener("pointerdown", onDown);
  }, [open, step.kind]);

  if (session.status !== "signed_in") return null;
  const demo = session.isDemo;

  const close = () => {
    setOpen(false);
    setStep({ kind: "menu" });
    buttonRef.current?.focus();
  };

  const run = async (label: string, action: () => Promise<void>, failure: string) => {
    setStep({ kind: "busy", label });
    try {
      await action();
      close();
    } catch {
      setStep({ kind: "error", message: failure });
    }
  };

  const deleteAndLeave = () =>
    run(
      demo ? "Ending the demo…" : "Deleting your data…",
      async () => {
        await api.deleteMe();
        await signOutUser();
        navigate("/");
      },
      demo ? "We couldn't end the demo. Try again." : "We couldn't delete your data. Nothing was signed out; try again.",
    );

  return (
    <div
      className="account"
      ref={rootRef}
      onKeyDown={(e) => {
        if (e.key === "Escape" && open) {
          e.preventDefault();
          close();
        }
      }}
    >
      <button
        ref={buttonRef}
        type="button"
        className="account__chip"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => (open ? close() : setOpen(true))}
      >
        <span className="account__avatar" data-demo={demo} aria-hidden="true">
          {demo ? "Demo" : initials(session.name)}
        </span>
        <span className="visually-hidden">{demo ? "Demo session" : "Your account"}</span>
      </button>
      {open && (
        <div className="account__panel" id={panelId} ref={panelRef} role="group" aria-label={demo ? "Demo session" : "Your account"}>
          <p className="account__who">
            {demo ? (
              <>
                <strong>Demo session</strong>
                <span>Sample readers, nothing tied to you.</span>
              </>
            ) : (
              <>
                <strong>{session.name ?? "Signed in"}</strong>
                <span>Signed in with Google</span>
              </>
            )}
          </p>
          {step.kind === "menu" && (
            <div className="account__actions">
              <button
                type="button"
                className="account__action"
                onClick={() => {
                  // Keep the demo persona: the profile shows that sample reader's model.
                  const persona = new URL(window.location.href).searchParams.get("persona");
                  close();
                  navigate(persona ? `/profile?persona=${encodeURIComponent(persona)}` : "/profile");
                }}
              >
                {demo ? "This reader's profile" : "Your reading profile"}
              </button>
              {!demo && (
                <button type="button" className="account__action" onClick={() => run("Preparing your export…", downloadExport, "The export didn't download. Try again.")}>
                  Export my data
                </button>
              )}
              {!demo && (
                <button type="button" className="account__action account__action--danger" onClick={() => setStep({ kind: "confirm-delete" })}>
                  Delete my data
                </button>
              )}
              {demo ? (
                <button type="button" className="account__action" onClick={deleteAndLeave}>
                  End demo
                </button>
              ) : (
                <button type="button" className="account__action" onClick={() => run("Signing out…", signOutUser, "Sign-out failed. Try again.")}>
                  Sign out
                </button>
              )}
            </div>
          )}
          {step.kind === "confirm-delete" && (
            <div className="account__confirm" role="alert">
              <p>Delete everything ReadLayer knows about you and your account? This can't be undone.</p>
              <div className="account__confirm-actions">
                <button type="button" className="btn btn--sm" onClick={() => setStep({ kind: "menu" })}>
                  Keep my data
                </button>
                <button type="button" className="btn btn--sm btn--danger" onClick={deleteAndLeave}>
                  Delete everything
                </button>
              </div>
            </div>
          )}
          {step.kind === "busy" && (
            <p className="account__status" role="status">
              {step.label}
            </p>
          )}
          {step.kind === "error" && (
            <div className="account__confirm" role="alert">
              <p>{step.message}</p>
              <button type="button" className="btn btn--sm" onClick={() => setStep({ kind: "menu" })}>
                Back
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
