/**
 * What Gloss reads, and how (decision 61): the "What you can read" list and the caps the media
 * copy quotes. Since decision 54 short videos and podcasts open in Gloss with notes; longer ones
 * open where they play. The caps equal production's MEDIA_MAX_VIDEO_S / MEDIA_MAX_AUDIO_S (a
 * vitest reads `apps/api/deploy.env.yaml`). The hero's chips are `formats.ts`, kept in step.
 * Every entry gets notes (a vitest checks), so the list shows "With notes" on each.
 */
export const VIDEO_CAP_MIN = 10;
export const PODCAST_CAP_MIN = 12;

export interface Format {
  what: string;
  /** The hero chip's label. */
  chip: string;
  notes: boolean;
  detail: string;
}

export const FORMATS: readonly Format[] = [
  { what: "Articles", chip: "Articles", notes: true, detail: "From your For you feed and the library." },
  { what: "Any link you paste", chip: "Any link", notes: true, detail: "Paste it into Read any link." },
  {
    what: "YouTube videos",
    chip: "Short videos",
    notes: true,
    detail: `With a transcript, up to ${VIDEO_CAP_MIN} minutes; longer ones open on YouTube.`,
  },
  {
    what: "Podcast episodes (Apple Podcasts)",
    chip: "Podcasts",
    notes: true,
    detail: `With a transcript, up to ${PODCAST_CAP_MIN} minutes; longer ones open where they play.`,
  },
  { what: "News pages in Chrome", chip: "Chrome extension", notes: true, detail: "Through the Gloss extension." },
];
