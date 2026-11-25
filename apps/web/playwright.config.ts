import { defineConfig, devices } from "@playwright/test";
export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 120_000,
  webServer: [
    {
      command: ".venv/bin/python -B scripts/serve_e2e.py",
      cwd: "../..",
      url: "http://127.0.0.1:8780/health/live",
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: "npm run dev -- --host localhost --strictPort",
      url: "http://localhost:5273",
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
  use: { baseURL: "http://localhost:5273", trace: "retain-on-failure", actionTimeout: 10_000 },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
