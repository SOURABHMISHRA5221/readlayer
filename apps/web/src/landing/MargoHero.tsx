import { EYES, MOUTH, type MargoMood } from "../components/Margo";

/** The moods the hero cycles through; every face is drawn, the current one is shown. */
export type HeroMood = Extract<MargoMood, "idle" | "think" | "happy">;
const MOODS: readonly HeroMood[] = ["idle", "think", "happy"];

interface MargoHeroProps {
  mood: HeroMood;
  className?: string;
}

/**
 * Margo as a character (decision 44): the logo's body, fold, swipe and faces, plus one arm
 * holding a small note card low and out, as if handing the reader the note. The landing mirrors
 * it so the note reaches into the demo sheet. Faces cross-fade on a mood
 * change (opacity only; instant under reduced motion). Always decorative.
 */
export function MargoHero({ mood, className = "" }: MargoHeroProps) {
  return (
    <svg
      className={`margo margo-hero${className ? ` ${className}` : ""}`}
      viewBox="0 0 104 96"
      aria-hidden="true"
      focusable="false"
    >
      <g transform="translate(2 14)">
        <path className="margo__swipe" d="M8 55.5 q24 -5 48 0 v4 q-24 -4.5 -48 0z" />
        {/* The arm goes behind the body, so it starts from inside the page's edge. */}
        <path className="margo-hero__arm" d="M46 36 q14 1 20 15" />
        <path
          className="margo__body"
          d="M17 8 h22 l11 11 v29 a6 6 0 0 1 -6 6 h-27 a6 6 0 0 1 -6 -6 v-34 a6 6 0 0 1 6 -6z"
        />
        <path className="margo__fold" d="M39 8 v7 a4 4 0 0 0 4 4 h7" />
        {MOODS.map((m) => (
          <g key={m} className={`margo-hero__face${m === mood ? " is-on" : ""}`}>
            {EYES[m]}
            {MOUTH[m] && <path className="margo__mouth" d={MOUTH[m]} />}
            {m === "think" && (
              <>
                <circle className="margo__dot" cx="50" cy="2" r="2.2" />
                <circle className="margo__dot" cx="55" cy="-3" r="1.6" />
              </>
            )}
            {m === "happy" && (
              <>
                <circle className="margo__cheek" cx="20" cy="40" r="3" />
                <circle className="margo__cheek" cx="44" cy="40" r="3" />
              </>
            )}
          </g>
        ))}
      </g>
      {/* The note in Margo's hand: a tiny card with a highlighted line. */}
      <g className="margo-hero__note" transform="rotate(10 86 76)">
        <rect className="margo-hero__card" x="72" y="64" width="28" height="22" rx="3" />
        <rect className="margo-hero__hl" x="76" y="69" width="14" height="4" rx="1" />
        <path className="margo-hero__line" d="M76 77.5 h19 M76 82 h12" />
      </g>
      <circle className="margo-hero__hand" cx="69" cy="66" r="3.4" />
    </svg>
  );
}

/** The hero's mood for each Read-as persona: more to explain, more thinking (vitest). */
export const PERSONA_MOOD = {
  newcomer: "think",
  trader: "idle",
  policy_student: "happy",
} as const satisfies Record<string, HeroMood>;
