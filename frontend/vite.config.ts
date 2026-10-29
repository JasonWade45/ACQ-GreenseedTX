import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { readFileSync } from "node:fs";

// One source of truth: the version the sidebar shows is the packaged one.
const { version } = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf8")) as {
  version: string;
};

export default defineConfig({
  plugins: [react()],
  // The release verifier expects exactly one script and one stylesheet in
  // index.html, so the app ships as a single bundle plus lazy route chunks.
  build: { chunkSizeWarningLimit: 600 },
  define: { __APP_VERSION__: JSON.stringify(version) },
  server: { host: "127.0.0.1", proxy: { "/api": "http://127.0.0.1:8000" } },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test-setup.ts"],
    css: false,
    include: ["src/**/*.test.tsx"],
  },
});
