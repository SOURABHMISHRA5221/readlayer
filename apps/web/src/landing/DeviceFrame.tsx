import { useEffect, useRef, useState, type ReactNode } from "react";

import { useMediaQuery } from "../hooks/useMediaQuery";
import { CLIP_BASE } from "./Clip";

/**
 * Device frames for full-window captures (decision 46e): a laptop, an external monitor and a
 * phone, drawn in CSS (no stock images), one family across the page with one subtle shadow.
 * Laptop and monitor screens are 16:10 (the 1440×900 captures); the phone's is 390:844. The frame
 * is decorative; the picture or clip inside carries the meaning.
 */
export function DeviceFrame({ kind, children }: { kind: "laptop" | "monitor" | "phone"; children: ReactNode }) {
  return (
    <div className={`lp-device lp-device--${kind}`}>
      <div className="lp-device__screen">{children}</div>
      {kind === "laptop" && <div className="lp-device__base" aria-hidden="true" />}
      {kind === "monitor" && <div className="lp-device__stand" aria-hidden="true" />}
    </div>
  );
}

/** How close a still must come before it loads: tighter than the browser's own lazy margin, so
 * nothing below the hero is fetched in the first view (decision 46e round 1 item 4). */
const NEAR_MARGIN = "200px 0px";

/** A full-window still at 1x and 2x, AVIF then WebP, explicit size, rendered only when near. */
export function Still({ name, width, height, alt }: { name: string; width: number; height: number; alt: string }) {
  const box = useRef<HTMLSpanElement>(null);
  const [near, setNear] = useState(false);
  useEffect(() => {
    const el = box.current;
    if (!el || near) return;
    if (typeof IntersectionObserver === "undefined") {
      setNear(true);
      return;
    }
    const io = new IntersectionObserver((e) => e.some((x) => x.isIntersecting) && setNear(true), { rootMargin: NEAR_MARGIN });
    io.observe(el);
    return () => io.disconnect();
  }, [near]);
  const set = (ext: string) => `${CLIP_BASE}/${name}.${ext} 1x, ${CLIP_BASE}/${name}@2x.${ext} 2x`;
  if (!near) return <span ref={box} className="lp-still lp-still--pending" role="img" aria-label={alt} />;
  return (
    <picture>
      <source type="image/avif" srcSet={set("avif")} />
      <source type="image/webp" srcSet={set("webp")} />
      <img className="lp-still" src={`${CLIP_BASE}/${name}.webp`} width={width} height={height} alt={alt} loading="lazy" decoding="async" />
    </picture>
  );
}

/** Wide enough for the monitor and laptop pair; below this, one phone. */
export const DESKTOP_PAIR_QUERY = "(min-width: 1024px)";

/**
 * "See it in action" (decision 46e S2): the whole Gloss window on an external monitor (the For you
 * feed) and a laptop (the reader with a note open); on smaller screens one phone with the bottom
 * sheet. Each device renders only its own pictures, so a phone never downloads the desktop pair.
 */
export function SeeItInAction() {
  const wide = useMediaQuery(DESKTOP_PAIR_QUERY);
  return (
    <section className="lp-section lp-action" aria-labelledby="lp-action-title">
      <h2 id="lp-action-title" className="lp-section__title">
        See it in action
      </h2>
      <figure className="lp-action__figure">
        {wide ? (
          <div className="lp-action__pair">
            <DeviceFrame kind="monitor">
              <Still
                name="shot-feed"
                width={1440}
                height={900}
                alt="The Gloss For you feed on a monitor: articles, videos and podcasts picked for a software engineer learning economics, each with the new ideas it teaches."
              />
            </DeviceFrame>
            <DeviceFrame kind="laptop">
              <Still
                name="shot-reader"
                width={1440}
                height={900}
                alt="The Gloss reader on a laptop: an Economic Times paragraph about a 25 bps rate hike, with the note on Basis points open in the margin, its Background using a software analogy."
              />
            </DeviceFrame>
          </div>
        ) : (
          <DeviceFrame kind="phone">
            <Still
              name="shot-phone"
              width={390}
              height={844}
              alt="The Gloss reader on a phone: the note on Basis points as a sheet that slides up from the bottom of the article."
            />
          </DeviceFrame>
        )}
        <figcaption className="lp-action__caption">
          Gloss on an Economic Times article. The article's words are unchanged; the notes are ours.
        </figcaption>
      </figure>
    </section>
  );
}
