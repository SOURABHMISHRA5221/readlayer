import { CLIP_BASE } from "./Clip";

/**
 * The reader on a laptop and a phone (decision 44 V2): real screenshots from the live site
 * (tools/shots/landing_media.py), a short snippet of the demo article, its source credited.
 * Frames are CSS, not stock art. Below the fold, so both images are lazy.
 */
function Shot({ name, width, height, alt }: { name: string; width: number; height: number; alt: string }) {
  const src = (ext: string) => `${CLIP_BASE}/${name}.${ext} 1x, ${CLIP_BASE}/${name}@2x.${ext} 2x`;
  return (
    <picture>
      <source type="image/avif" srcSet={src("avif")} />
      <source type="image/webp" srcSet={src("webp")} />
      <img
        className="lp-shot__img"
        src={`${CLIP_BASE}/${name}.webp`}
        width={width}
        height={height}
        alt={alt}
        loading="lazy"
        decoding="async"
      />
    </picture>
  );
}

export function ProductShot() {
  return (
    <section className="lp-shot" aria-label="Gloss in the reader">
      <figure className="lp-shot__figure">
        <div className="lp-shot__devices">
          <div className="lp-shot__laptop">
            <div className="lp-shot__screen">
              <Shot
                name="shot-desktop"
                width={760}
                height={441}
                alt="The Gloss reader on a laptop: a paragraph about a 25 bps rate hike, with the note on “Basis points” open in the margin, a Background with a software analogy and what the author is saying."
              />
            </div>
            <div className="lp-shot__base" aria-hidden="true" />
          </div>
          <div className="lp-shot__phone">
            <Shot
              name="shot-phone"
              width={300}
              height={650}
              alt="The same note on a phone, as a sheet that slides up from the bottom of the article."
            />
          </div>
        </div>
        <figcaption className="lp-shot__caption">
          Gloss on an Economic Times article. The article's words are unchanged; the note is ours.
        </figcaption>
      </figure>
    </section>
  );
}
