import { useEffect, useRef, useState, type CSSProperties } from "react";

import { useMediaQuery } from "../hooks/useMediaQuery";

/**
 * A short silent loop of the whole Gloss window, recorded from the live app (decision 44 V4,
 * decision 46e). Nothing loads until the clip is near the viewport (not even the poster, which a
 * video fetches eagerly); it plays while on screen and pauses when it leaves; a visible Pause
 * button stops it for good (WCAG 2.2.2). If the browser blocks autoplay, the poster shows a "Tap
 * to play" button. Under reduced motion only the poster is shown.
 *
 * To guide the eye there is no crop: while the clip plays, the frame zooms gently toward the area
 * of action (`focus`, ≤ 1.15×) with a soft spotlight, eased in after the start and out before the
 * loop. Pausing, leaving the viewport or reduced motion stop both. The video is decorative next
 * to the step's text, so it is hidden from assistive tech.
 */
export const CLIP_BASE = "/landing";
/** Phones and tablets get the 1x encode (a 2880px video in a ~360px tile is wasted decode). */
export const CLIP_SMALL_QUERY = "(max-width: 1023px)";
export const MAX_ZOOM = 1.15;
/** The part of each loop that is zoomed in (fractions of its duration). */
const ZOOM_FROM = 0.18;
const ZOOM_UNTIL = 0.82;

/** The area of action, as fractions of the frame (from the recording; tools/shots/clip_focus.json). */
export interface Focus {
  x: number;
  y: number;
  w: number;
  h: number;
}

interface ClipProps {
  name: string;
  /** What the clip shows, for the Pause and Play buttons' names. */
  label: string;
  width: number;
  height: number;
  focus?: Focus;
}

export function Clip(props: ClipProps) {
  const reduced = useMediaQuery("(prefers-reduced-motion: reduce)");
  return <ClipView {...props} reducedMotion={reduced} />;
}

/** How far to zoom so the focus box fills more of the frame, never past MAX_ZOOM. */
export function zoomFor(focus: Focus): number {
  const fill = Math.max(focus.w, focus.h);
  return Math.min(MAX_ZOOM, Math.max(1, 0.8 / Math.max(fill, 0.01)));
}

export function ClipView({ name, label, width, height, focus, reducedMotion }: ClipProps & { reducedMotion: boolean }) {
  const box = useRef<HTMLDivElement>(null);
  const video = useRef<HTMLVideoElement>(null);
  const [near, setNear] = useState(false);
  const [visible, setVisible] = useState(false);
  const [paused, setPaused] = useState(false);
  const [blocked, setBlocked] = useState(false);
  const [zoomed, setZoomed] = useState(false);
  const poster = `${CLIP_BASE}/${name}-poster.webp`;
  const playing = near && visible && !paused && !blocked;

  useEffect(() => {
    const el = box.current;
    if (reducedMotion || !el || typeof IntersectionObserver === "undefined") return;
    const nearIo = new IntersectionObserver((e) => e.some((x) => x.isIntersecting) && setNear(true), {
      rootMargin: "300px 0px",
    });
    const seenIo = new IntersectionObserver((e) => setVisible(e.some((x) => x.isIntersecting)), { threshold: 0.25 });
    nearIo.observe(el);
    seenIo.observe(el);
    return () => {
      nearIo.disconnect();
      seenIo.disconnect();
    };
  }, [reducedMotion]);

  // Sources are added only when near; load them once they are in the DOM.
  useEffect(() => {
    if (near) video.current?.load();
  }, [near]);

  useEffect(() => {
    const v = video.current;
    if (!v || !near) return;
    if (visible && !paused && !blocked) {
      void v.play()?.catch((e: unknown) => {
        // Autoplay refused (e.g. data saver): the poster stays with a Tap to play button.
        if (e instanceof DOMException && e.name === "NotAllowedError") setBlocked(true);
      });
    } else v.pause();
  }, [near, visible, paused, blocked]);

  // The zoom follows the loop's own clock, so it eases out before every restart.
  useEffect(() => {
    const v = video.current;
    if (!v || !focus || !playing) {
      setZoomed(false);
      return;
    }
    const tick = () => {
      const phase = v.duration ? v.currentTime / v.duration : 0;
      setZoomed(phase >= ZOOM_FROM && phase <= ZOOM_UNTIL);
    };
    v.addEventListener("timeupdate", tick);
    return () => v.removeEventListener("timeupdate", tick);
  }, [focus, playing]);

  if (reducedMotion) {
    return (
      <div className="lp-clip" ref={box}>
        <img className="lp-clip__media" src={poster} alt="" width={width} height={height} loading="lazy" decoding="async" />
      </div>
    );
  }

  const focusStyle = focus
    ? ({
        "--clip-fx": `${(focus.x + focus.w / 2) * 100}%`,
        "--clip-fy": `${(focus.y + focus.h / 2) * 100}%`,
        "--clip-zoom": zoomFor(focus),
      } as CSSProperties)
    : undefined;

  return (
    <div className={`lp-clip${zoomed ? " lp-clip--zoomed" : ""}`} ref={box} style={focusStyle}>
      <video
        ref={video}
        className="lp-clip__media"
        width={width}
        height={height}
        poster={near ? poster : undefined}
        muted
        loop
        playsInline
        preload="none"
        aria-hidden="true"
      >
        {/* Small screens first: browsers without <source media> support play the first one. */}
        {near && <source media={CLIP_SMALL_QUERY} src={`${CLIP_BASE}/${name}-1x.webm`} type="video/webm" />}
        {near && <source media={CLIP_SMALL_QUERY} src={`${CLIP_BASE}/${name}-1x.mp4`} type="video/mp4" />}
        {near && <source src={`${CLIP_BASE}/${name}.webm`} type="video/webm" />}
        {near && <source src={`${CLIP_BASE}/${name}.mp4`} type="video/mp4" />}
      </video>
      {focus && <div className="lp-clip__spot" aria-hidden="true" />}
      {blocked ? (
        <button
          type="button"
          className="lp-clip__play"
          aria-label={`Play the clip: ${label}`}
          onClick={() => {
            setBlocked(false);
            void video.current?.play()?.catch(() => setBlocked(true));
          }}
        >
          <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" focusable="false">
            <path d="M4 2.5v11l9-5.5z" fill="currentColor" />
          </svg>
          Tap to play
        </button>
      ) : (
        <button
          type="button"
          className="lp-clip__toggle"
          aria-pressed={paused}
          aria-label={`Pause the clip: ${label}`}
          onClick={() => setPaused((p) => !p)}
        >
          {paused ? (
            <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true" focusable="false">
              <path d="M4 2.5v11l9-5.5z" fill="currentColor" />
            </svg>
          ) : (
            <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true" focusable="false">
              <path d="M4 2.5h3v11H4zM9 2.5h3v11H9z" fill="currentColor" />
            </svg>
          )}
        </button>
      )}
    </div>
  );
}
