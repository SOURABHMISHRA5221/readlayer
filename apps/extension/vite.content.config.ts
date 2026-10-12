import { resolve } from "node:path";

import { defineConfig } from "vite";

/** The content script: one classic-script IIFE (no imports), appended to dist/ after the main build. */
export default defineConfig({
  build: {
    outDir: "dist",
    emptyOutDir: false,
    target: "chrome120",
    lib: {
      entry: resolve(__dirname, "src/content.ts"),
      formats: ["iife"],
      name: "ReadLayerContent",
      fileName: () => "content.js",
    },
  },
});
