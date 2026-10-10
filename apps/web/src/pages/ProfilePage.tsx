import { useCallback, useEffect, useRef, useState } from "react";

import { AccountMenu } from "../components/AccountMenu";
import { ArrowLeft } from "../components/Icons";
import { EditBox } from "../components/profile/EditBox";
import { KnowledgeMap } from "../components/profile/KnowledgeMap";
import { Segmented } from "../components/Segmented";
import { StateView } from "../components/StateView";
import { ThemeToggle } from "../components/ThemeToggle";
import { Wordmark } from "../components/Wordmark";
import { api } from "../lib/api";
import { signOutUser, useIsDemo } from "../lib/auth";
import { domainLabel } from "../lib/format";
import { personaOf, personaParam, readerPersona } from "../lib/personas";
import { FRAMES, profileApi, type Domain, type Frame, type Profile } from "../lib/profileApi";
import { BUSINESS_DOMAINS } from "../lib/taxonomy";
import { thetaPercent, thetaText, thetaWord } from "../lib/profileFormat";
import { navigate, withParams } from "../lib/router";
import "../styles/profile.css";

/** The reader's view of their own model (DESIGN §15.1): what we think they know, how it's
 * changing, and how to correct it. Demo readers see their sample reader's profile. */
export default function ProfilePage({ url }: { url: URL }) {
  const isDemo = useIsDemo();
  const persona = readerPersona(url, isDemo);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [failed, setFailed] = useState(false);
  const [version, setVersion] = useState(0);
  const refresh = useCallback(() => setVersion((v) => v + 1), []);

  useEffect(() => {
    document.title = "Your reading profile · ReadLayer";
  }, []);

  useEffect(() => {
    const ctrl = new AbortController();
    profileApi
      .profile(persona, ctrl.signal)
      .then((p) => {
        setProfile(p);
        setFailed(false);
      })
      .catch(() => !ctrl.signal.aborted && setFailed(true));
    return () => ctrl.abort();
  }, [persona, version]);

  const libraryHref = withParams(new URL("/", window.location.origin), { persona: personaParam(persona) });
  const name = persona ? personaOf(persona).label : null;

  return (
    <div className="profile">
      <header className="profile__bar">
        <a
          className="profile__back"
          href={libraryHref}
          onClick={(e) => {
            e.preventDefault();
            navigate(libraryHref);
          }}
        >
          <ArrowLeft size={16} /> Library
        </a>
        <Wordmark />
        <div className="profile__bar-end">
          <ThemeToggle />
          <AccountMenu />
        </div>
      </header>
      <main className="profile__main" id="main">
        <p className="eyebrow">{name ? `${name} · demo` : "Your reading profile"}</p>
        <h1 className="profile__title">{name ? `What ${name} knows` : "What we think you know"}</h1>
        {failed && (
          <StateView title="Your profile didn't load" role="alert">
            Try again in a moment.
          </StateView>
        )}
        {!profile && !failed && <div className="skeleton profile__skeleton" aria-busy="true" aria-label="Loading your profile" />}
        {profile && (
          <>
            {profile.summary.learning_paused && (
              <p className="profile__banner" role="status">
                Learning is paused: reading doesn't change your profile until you resume it below.
              </p>
            )}
            <section className="summary" aria-labelledby="summary-title">
              <h2 id="summary-title" className="visually-hidden">
                Summary
              </h2>
              <p className="summary__text">{profile.summary.text}</p>
            </section>
            <DomainBars profile={profile} />
            <KnowledgeMap
              persona={persona}
              domains={profile.domains.filter((d) => d.concepts > 0).map((d) => d.domain)}
              initial={(profile.summary.top_domain as Domain) ?? "finance"}
              refreshKey={version}
              onChanged={refresh}
            />
            <WeekCard profile={profile} demo={!!persona} />
            <Frames profile={profile} demoName={name} onChanged={refresh} />
            <Preferences profile={profile} onChanged={refresh} disabled={!!persona} />
            <EditBox persona={persona} personaName={name} onChanged={refresh} />
            <DataControls demo={isDemo} paused={profile.summary.learning_paused} onChanged={refresh} />
          </>
        )}
      </main>
    </div>
  );
}


type DomainRow = Profile["domains"][number];

/** Rated domains and the reader's chosen interests come first; with neither, the four core
 *  domains. The rest of the 14 sit behind "Other domains" so the page stays short. */
function splitDomains(rows: DomainRow[]): [DomainRow[], DomainRow[]] {
  const mine = rows.filter((d) => d.rated || d.interest >= 0.5);
  const primary = mine.length ? mine : rows.filter((d) => BUSINESS_DOMAINS.includes(d.domain));
  return [primary, rows.filter((d) => !primary.includes(d))];
}

function DomainBars({ profile }: { profile: Profile }) {
  const [primary, rest] = splitDomains(profile.domains);
  return (
    <section className="bars" aria-labelledby="bars-title">
      <h2 id="bars-title" className="profile__h2">
        Ability and interest
      </h2>
      <DomainList rows={primary} />
      {rest.length > 0 && (
        <details className="bars__more">
          <summary>Other domains ({rest.length})</summary>
          <DomainList rows={rest} />
        </details>
      )}
      <p className="profile__note">Ability is on a scale from −2 (new to it) to +2 (advanced).</p>
    </section>
  );
}

function DomainList({ rows }: { rows: DomainRow[] }) {
  return (
      <ul className="bars__list">
        {rows.map((d) => (
          <li key={d.domain} className="bars__row">
            <span className="bars__domain">{domainLabel(d.domain)}</span>
            <span className="bars__pair">
              <span className="bars__bar" aria-hidden="true">
                {d.rated && (
                  <span className="bars__fill bars__fill--ability" style={{ width: `${thetaPercent(d.theta)}%` }} />
                )}
              </span>
              <span className="bars__value">
                {d.rated ? `Ability ${thetaText(d.theta)} · ${thetaWord(d.theta)}` : "Ability: not rated yet"}
              </span>
              <span className="bars__bar" aria-hidden="true">
                <span className="bars__fill bars__fill--interest" style={{ width: `${Math.round(d.interest * 100)}%` }} />
              </span>
              <span className="bars__value">Interest {Math.round(d.interest * 100)}%</span>
            </span>
          </li>
        ))}
      </ul>
  );
}

function WeekCard({ profile, demo }: { profile: Profile; demo: boolean }) {
  const moved = profile.week.moved_up;
  const trend = profile.week.trend;
  return (
    <section className="week" aria-labelledby="week-title">
      <h2 id="week-title" className="profile__h2">
        This week
      </h2>
      {moved.length ? (
        <ul className="week__moved">
          {moved.map((m) => (
            <li key={m.concept_id}>
              <strong>{m.label}</strong> moved from {m.from} to {m.to}
            </li>
          ))}
        </ul>
      ) : (
        <p className="profile__note">Nothing moved up a level yet this week.</p>
      )}
      {trend.length > 0 && (
        <table className="week__trend">
          <caption>Notes per 1,000 words{demo ? " (this demo session)" : ""}: falling means the overlay is learning</caption>
          <thead>
            <tr>
              <th scope="col">Week</th>
              <th scope="col">Notes per 1,000 words</th>
            </tr>
          </thead>
          <tbody>
            {trend.map((t) => (
              <tr key={t.week}>
                <td>{t.week}</td>
                <td className="tnum">{t.annotations_per_1000_words.toFixed(1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function Frames({ profile, demoName, onChanged }: { profile: Profile; demoName: string | null; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const chosen = profile.thinks_in;
  if (demoName) {
    return (
      <section className="frames" aria-labelledby="frames-title">
        <h2 id="frames-title" className="profile__h2">
          Analogies
        </h2>
        <p>
          {demoName} thinks in <strong>{chosen.join(", ")}</strong>. Describe yourself below to try another
          frame for this demo session.
        </p>
      </section>
    );
  }
  const [error, setError] = useState<string | null>(null);
  const toggle = async (f: Frame) => {
    const next = chosen.includes(f) ? chosen.filter((x) => x !== f) : chosen.length < 3 ? [...chosen, f] : chosen;
    if (next === chosen) return;
    setBusy(true);
    setError(null);
    try {
      await profileApi.settings({ thinks_in: next });
      onChanged();
    } catch {
      setError("That didn't save. Try again.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="frames" aria-labelledby="frames-title">
      <h2 id="frames-title" className="profile__h2">
        Analogies from
      </h2>
      <p className="profile__note">Up to three. Explanations only ever draw analogies from these.</p>
      <div className="frames__chips" role="group" aria-labelledby="frames-title">
        {FRAMES.map((f) => {
          const on = chosen.includes(f);
          return (
            <button
              key={f}
              type="button"
              className="frames__chip"
              aria-pressed={on}
              disabled={busy || (!on && chosen.length >= 3)}
              onClick={() => void toggle(f)}
            >
              {f}
            </button>
          );
        })}
      </div>
      {error && (
        <p className="welcome__error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

function Preferences({ profile, onChanged, disabled }: { profile: Profile; onChanged: () => void; disabled: boolean }) {
  const [error, setError] = useState<string | null>(null);
  const set = async (changes: Parameters<typeof profileApi.settings>[0]) => {
    setError(null);
    try {
      await profileApi.settings(changes);
      onChanged();
    } catch {
      setError("That didn't save. Try again.");
    }
  };
  if (disabled) return null; // demo sessions change these through the description box
  return (
    <section className="prefs" aria-labelledby="prefs-title">
      <h2 id="prefs-title" className="profile__h2">
        Preferences
      </h2>
      <Segmented
        label="Explanation length"
        options={[
          { key: "short" as const, label: "Short" },
          { key: "normal" as const, label: "Normal" },
          { key: "detailed" as const, label: "Detailed" },
        ]}
        value={profile.settings.explanation_style}
        onChange={(v) => void set({ explanation_style: v })}
      />
      <Segmented
        label="Notes"
        options={[
          { key: "minimal" as const, label: "Fewer" },
          { key: "balanced" as const, label: "Balanced" },
          { key: "guided" as const, label: "More" },
        ]}
        value={profile.settings.density}
        onChange={(v) => void set({ density: v })}
      />
      {error && (
        <p className="welcome__error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

function DataControls({ demo, paused, onChanged }: { demo: boolean; paused: boolean; onChanged: () => void }) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const deleteButton = useRef<HTMLButtonElement>(null);
  const cancel = () => {
    setConfirming(false);
    requestAnimationFrame(() => deleteButton.current?.focus());
  };

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
      navigate("/", { replace: true });
    } catch {
      setMessage("We couldn't delete your data. Try again.");
      setBusy(false);
    }
  };

  return (
    <section className="data" aria-labelledby="data-title">
      <h2 id="data-title" className="profile__h2">
        Your data
      </h2>
      {!demo && (
        <label className="data__toggle">
          <input
            type="checkbox"
            checked={paused}
            onChange={async (e) => {
              setMessage(null);
              try {
                await profileApi.settings({ learning_paused: e.target.checked });
                onChanged();
              } catch {
                setMessage("Pausing didn't save. Try again.");
              }
            }}
          />
          <span>Pause learning (reading won't change your profile)</span>
        </label>
      )}
      <div className="data__row">
        {!demo && (
          <button type="button" className="btn" onClick={() => void exportData()} disabled={busy}>
            Export my data
          </button>
        )}
        {!confirming ? (
          <button type="button" ref={deleteButton} className="btn btn--danger" onClick={() => setConfirming(true)} disabled={busy}>
            {demo ? "End demo" : "Delete my data"}
          </button>
        ) : (
          <span className="data__confirm" role="group" aria-label="Confirm delete" onKeyDown={(e) => e.key === "Escape" && cancel()}>
            <span>{demo ? "End the demo and delete what it recorded?" : "Delete everything ReadLayer knows about you? This can't be undone."}</span>
            <button type="button" className="btn" autoFocus onClick={cancel} disabled={busy}>
              Cancel
            </button>
            <button type="button" className="btn btn--danger" onClick={() => void deleteAll()} disabled={busy}>
              {demo ? "End demo" : "Delete everything"}
            </button>
          </span>
        )}
      </div>
      {message && (
        <p className="welcome__error" role="alert">
          {message}
        </p>
      )}
    </section>
  );
}
