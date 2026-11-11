import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// The dashboard is served by the local FastAPI process in production. During
// development Vite proxies API + WebSocket traffic to that same process, so the
// UI always talks to the real backend — there is no mock server.
const BACKEND = "http://127.0.0.1:8420";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    host: "127.0.0.1",
    proxy: {
      "/api": { target: BACKEND, changeOrigin: false },
      "/ws": { target: BACKEND, ws: true, changeOrigin: false },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    chunkSizeWarningLimit: 900,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test/setup.ts",
    css: false,
    restoreMocks: true,
  },
});
