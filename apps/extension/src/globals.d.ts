import type { Prepared } from "./content";

declare global {
  // The content script's entry points, in the extension's isolated world on the page.
  var __readlayer: { prepare(): Prepared; start(config: { webBase: string }): Promise<void> } | undefined;
}
