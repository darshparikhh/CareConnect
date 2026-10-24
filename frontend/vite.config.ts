/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// https://vitejs.dev/config/
// Dev server runs on 5173, which the FastAPI backend already allow-lists for CORS.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
  },
  test: {
    // Component tests need a DOM; jsdom provides one in-process.
    environment: "jsdom",
    globals: true,
    // Imports @testing-library/jest-dom matchers once per test run.
    setupFiles: "./src/test/setup.ts",
    css: false,
  },
});
