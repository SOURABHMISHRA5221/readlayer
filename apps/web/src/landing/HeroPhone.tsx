import { useMediaQuery } from "../hooks/useMediaQuery";
import { CLIP_BASE } from "./Clip";

/** Wide enough for the phone beside the card's corner (decision 46 P3). */
export const HERO_PHONE_QUERY = "(min-width: 1024px)";

/**
 * The reader on a phone (decision 44 V2, decision 46 P3): a real screenshot from the live site
 * (tools/shots/landing_media.py) in a CSS frame, peeking from the hero card's bottom-right
 * corner. Desktop only, and only rendered there, so phones never fetch it. Absolutely
 * positioned, so it never moves the layout.
 */
export function HeroPhone() {
  const wide = useMediaQuery(HERO_PHONE_QUERY);
  if (!wide) return null;
  const src = (ext: string) => `${CLIP_BASE}/shot-phone.${ext} 1x, ${CLIP_BASE}/shot-phone@2x.${ext} 2x`;
  return (
    <div className="lp-phone">
      <picture>
        <source type="image/avif" srcSet={src("avif")} />
        <source type="image/webp" srcSet={src("webp")} />
        <img
          className="lp-phone__img"
          src={`${CLIP_BASE}/shot-phone.webp`}
          width={300}
          height={650}
          alt="The same note in Gloss on a phone, as a sheet that slides up from the bottom of the article."
          decoding="async"
        />
      </picture>
    </div>
  );
}
