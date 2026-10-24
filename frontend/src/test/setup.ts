/**
 * Vitest setup: registers @testing-library/jest-dom matchers (toBeInTheDocument,
 * toHaveTextContent, etc.) and cleans up the rendered DOM between tests.
 * Referenced from vite.config.ts `test.setupFiles`.
 */
import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(() => {
  cleanup();
});
