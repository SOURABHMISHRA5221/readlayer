import { useEffect, useRef, useState } from "react";

import { useMediaQuery } from "../hooks/useMediaQuery";

/**
 * A short silent loop recorded from the real app (decision 44 V4). Nothing loads until the clip
 * is near the viewport (not even the poster, which a video fetches eagerly); it plays while on
 * screen and pauses when it leaves; a visible Pause button stops it for good (WCAG 2.2.2). Under
 * reduced motion only the poster is shown. The video is decorative next to the step's text, so
 * it is hidden from assistive tech.
 */
export const CLIP_BASE = "/landing";

interface ClipProps {
  name: string;
  /** What the clip shows, for the Pause button's name. */
  label: string;
  width: number;
  height: number;
}

export function Clip(props: ClipProps) {
  const reduced = useMediaQuery("(prefers-reduced-motion: reduce)");
  return <ClipView {...props} reducedMotion={reduced} />;
}

export function ClipView({ name, label, width, height, reducedMotion }: ClipProps & { reducedMotion: boolean }) {
  const box = useRef<HTMLDivElement>(null);
  const video = useRef<HTMLVideoElement>(null);
  const [near, setNear] = useState(false);
  const [visible, setVisible] = useState(false);
  const [paused, setPaused] = useState(false);
  const poster = `${CLIP_BASE}/${name}-poster.webp`;

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
    if (visible && !paused) void v.play()?.catch(() => undefined);
    else v.pause();
  }, [near, visible, paused]);

  return (
    <div className="lp-clip" ref={box}>
      {reducedMotion ? (
        <img className="lp-clip__media" src={poster} alt="" width={width} height={height} loading="lazy" decoding="async" />
      ) : (
        <>
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
            {near && <source src={`${CLIP_BASE}/${name}.webm`} type="video/webm" />}
            {near && <source src={`${CLIP_BASE}/${name}.mp4`} type="video/mp4" />}
          </video>
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
        </>
      )}
    </div>
  );
}
