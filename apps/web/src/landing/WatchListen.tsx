import { DeviceFrame, Still } from "./DeviceFrame";
import { PODCAST_CAP_MIN, VIDEO_CAP_MIN } from "./formatsFull";

/**
 * "Watch and listen" (decision 61 C): short videos and podcast episodes open in Gloss with a
 * transcript and the same notes (decision 54). The caveat is the reader's own: the transcript is
 * made automatically. The caps are production's (formatsFull.ts).
 */
export function WatchAndListen() {
  return (
    <section className="lp-section lp-split lp-watch" aria-labelledby="lp-watch-title">
      <div className="lp-split__copy">
        <h2 id="lp-watch-title" className="lp-section__title">
          Watch and listen
        </h2>
        <p className="lp-section__lede">
          YouTube videos up to {VIDEO_CAP_MIN} minutes and podcast episodes up to {PODCAST_CAP_MIN} minutes open in
          Gloss with a transcript and the same notes, explained for you.
        </p>
        <p className="lp-watch__more">
          Paste a YouTube link or an Apple Podcasts episode link into Read any link. Tap a time in the transcript to
          play from there. Longer ones open where they play.
        </p>
        <p className="lp-watch__fine">
          The transcript is made automatically and can contain errors; the recording is always the source.
        </p>
      </div>
      <figure className="lp-split__figure">
        <DeviceFrame kind="laptop">
          <Still
            name="shot-media"
            width={1440}
            height={900}
            alt="A short Fireship video open in Gloss: the player, the transcript with a time button on each paragraph, and the note on Decompiler open beside the highlighted word decompile."
          />
        </DeviceFrame>
      </figure>
    </section>
  );
}
