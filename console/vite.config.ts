/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The proxy serves the build at /console/. In dev, /v1 is forwarded to the proxy
// so the browser sees one origin and no CORS configuration is needed.
export default defineConfig({
  base: "/console/",
  plugins: [react()],
  server: { port: 5173, proxy: { "/v1": "http://127.0.0.1:8088", "/healthz": "http://127.0.0.1:8088" } },
  build: { outDir: "dist", sourcemap: false, chunkSizeWarningLimit: 700 },
  test: { environment: "jsdom", globals: true, setupFiles: ["./src/test-setup.ts"], css: false },
});
