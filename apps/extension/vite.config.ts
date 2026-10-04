import { defineConfig } from "vite";

// MV3 service worker as a single ES module; manifest.json is copied from public/.
export default defineConfig({
  build: {
    outDir: "dist",
    emptyOutDir: true,
    rollupOptions: {
      input: { background: "src/background.ts" },
      output: { entryFileNames: "[name].js", format: "es" },
    },
  },
});
