import { defineConfig, devices } from "@playwright/test";

// Browser smoke tests (frontend/e2e). They run against the built web UI served
// by the real backend, with a fixture vault and a scripted chat model — see
// scripts/e2e_server.py. Build first: `npm run build:web`, then `npm run test:e2e`.
const env = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env ?? {};
const PORT = Number(env.E2E_PORT ?? 8799);
const PYTHON = env.E2E_PYTHON ?? (env.CI ? "python" : "python3");
// Use an already installed Chromium (e.g. a sandbox image) instead of a download.
const executablePath = env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: env.CI ? 1 : 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    viewport: { width: 1280, height: 820 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 820 }, launchOptions: { executablePath } },
    },
  ],
  webServer: {
    command: `${PYTHON} ../scripts/e2e_server.py --port ${PORT}`,
    url: `http://127.0.0.1:${PORT}/health`,
    timeout: 120_000,
    reuseExistingServer: false,
    stdout: "pipe",
    stderr: "pipe",
  },
});
