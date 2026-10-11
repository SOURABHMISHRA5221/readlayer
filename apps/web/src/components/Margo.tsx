/**
 * Margo, Gloss's mascot: one ink outline and one teal swipe (docs/design/mockup.html, DESIGN
 * §19). Always decorative (aria-hidden). Lives in the margin, empty and error states and the
 * logo; never in article text, never on note cards, never animated while the reader reads.
 */
import type { ReactElement } from "react";

export type MargoMood = "idle" | "think" | "happy" | "oops" | "mark";

const EYES: Record<MargoMood, ReactElement> = {
  idle: (
    <>
      <circle className="margo__eye" cx="25" cy="33" r="3.2" />
      <circle className="margo__eye" cx="39" cy="33" r="3.2" />
    </>
  ),
  think: (
    <>
      <circle className="margo__eye" cx="27" cy="30" r="3.2" />
      <circle className="margo__eye" cx="41" cy="30" r="3.2" />
    </>
  ),
  happy: (
    <>
      <path className="margo__lid" d="M21.5 34 q3.5 -4.5 7 0" />
      <path className="margo__lid" d="M35.5 34 q3.5 -4.5 7 0" />
    </>
  ),
  oops: (
    <>
      <circle className="margo__eye" cx="25" cy="34" r="3.2" />
      <circle className="margo__eye" cx="39" cy="34" r="3.2" />
    </>
  ),
  mark: (
    <>
      <circle className="margo__eye" cx="25" cy="34" r="4" />
      <circle className="margo__eye" cx="39" cy="34" r="4" />
    </>
  ),
};

const MOUTH: Record<MargoMood, string | null> = {
  idle: "M28.5 40.5 q3.5 3 7 0",
  think: "M30 41.5 h5",
  happy: "M27 39.5 q5 5.5 10 0",
  oops: "M28.5 42.5 q3.5 -3 7 0",
  mark: null,
};

type Props = { mood?: MargoMood; size?: number; blink?: boolean; className?: string };

export function Margo({ mood = "idle", size = 32, blink = false, className = "" }: Props) {
  const mouth = MOUTH[mood];
  return (
    <svg
      className={`margo${blink && mood === "idle" ? " margo--blink" : ""}${className ? ` ${className}` : ""}`}
      width={size}
      height={size}
      viewBox="0 0 64 64"
      aria-hidden="true"
      focusable="false"
    >
      {mood === "mark" ? (
        <rect className="margo__swipe" x="9" y="52" width="46" height="7" rx="3.5" />
      ) : (
        <path className="margo__swipe" d="M8 55.5 q24 -5 48 0 v4 q-24 -4.5 -48 0z" />
      )}
      <path className="margo__body" d="M17 8 h22 l11 11 v29 a6 6 0 0 1 -6 6 h-27 a6 6 0 0 1 -6 -6 v-34 a6 6 0 0 1 6 -6z" />
      <path className="margo__fold" d="M39 8 v7 a4 4 0 0 0 4 4 h7" />
      {EYES[mood]}
      {mouth && <path className="margo__mouth" d={mouth} />}
      {mood === "think" && (
        <>
          <circle className="margo__dot" cx="50" cy="10" r="2.2" />
          <circle className="margo__dot" cx="56" cy="5" r="1.6" />
        </>
      )}
      {mood === "happy" && (
        <>
          <circle className="margo__cheek" cx="20" cy="40" r="3" />
          <circle className="margo__cheek" cx="44" cy="40" r="3" />
        </>
      )}
    </svg>
  );
}
