import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

// Local dev: the API runs on :8000 (make dev); proxying keeps the browser same-origin.
export default defineConfig(({ command, mode }) => {
  const env = loadEnv(mode, process.cwd(), "VITE_");
  // The emulator harness (make dev-emulator) must never reach a Hosting build.
  if (command === "build" && (env.VITE_USE_EMULATORS === "1" || process.env.VITE_USE_EMULATORS === "1")) {
    throw new Error("VITE_USE_EMULATORS is set: refusing to build for production");
  }
  return {
    plugins: [react()],
    server: { port: 5173, proxy: { "/v1": "http://127.0.0.1:8000" } },
  };
});
