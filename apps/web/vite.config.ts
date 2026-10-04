import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Local dev: the API runs on :8000 (make dev); proxying keeps the browser same-origin.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/v1": "http://127.0.0.1:8000" } },
});
