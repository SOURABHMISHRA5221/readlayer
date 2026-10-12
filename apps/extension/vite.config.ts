import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { defineConfig, loadEnv, type Plugin } from "vite";

/**
 * Worker (ES module) and popup. The content script is a separate IIFE build
 * (vite.content.config.ts): Chrome injects it as a classic script. manifest.json is written from
 * manifest.base.json with this build's web origins (externally_connectable), and
 * scripts/check-manifest.mjs fails the build if it ever gains host permissions or content scripts.
 */
function manifest(origins: string[]): Plugin {
  return {
    name: "readlayer-manifest",
    generateBundle() {
      const base = JSON.parse(readFileSync(resolve(__dirname, "manifest.base.json"), "utf8"));
      base.externally_connectable = { matches: origins.map((o) => `${o}/*`) };
      this.emitFile({ type: "asset", fileName: "manifest.json", source: `${JSON.stringify(base, null, 2)}\n` });
    },
  };
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, __dirname, "VITE_");
  const origins = (env.VITE_WEB_ORIGINS ?? "").split(",").map((o) => o.trim().replace(/\/$/, "")).filter(Boolean);
  if (!env.VITE_API_BASE || !origins.length) {
    throw new Error(`extension build (${mode}): VITE_API_BASE and VITE_WEB_ORIGINS are required (see apps/extension/.env.production)`);
  }
  return {
    plugins: [manifest(origins)],
    build: {
      outDir: "dist",
      emptyOutDir: true,
      target: "chrome120",
      modulePreload: false,
      rollupOptions: {
        input: { background: resolve(__dirname, "src/background.ts"), popup: resolve(__dirname, "popup.html") },
        output: { entryFileNames: "[name].js", chunkFileNames: "[name]-[hash].js", assetFileNames: "[name][extname]" },
      },
    },
  };
});
