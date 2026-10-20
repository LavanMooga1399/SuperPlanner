import { defineConfig, devices } from "@playwright/test";
import * as os from "node:os";
import * as path from "node:path";
import * as fs from "node:fs";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));

// Temp DB outside the repo (criterion 4.8); a fresh one per test session.
// The config is loaded by the runner and by every worker; share one temp dir through the env.
process.env.SP_E2E_TMP ??= fs.mkdtempSync(path.join(os.tmpdir(), "sp-e2e-"));
const tmpDir = process.env.SP_E2E_TMP;
const dbUrl = `sqlite:///${path.join(tmpDir, "e2e.db")}`;
const backendDir = path.resolve(here, "../../backend");
const frontendDir = path.resolve(here, "..");

process.env.PLAYWRIGHT_BROWSERS_PATH ??= "/opt/pw-browsers";

export default defineConfig({
  testDir: ".",
  testMatch: /.*\.spec\.ts$/,
  // PHASE2B 4.10: the accounts specs have their own config (playwright.accounts.config.ts).
  testIgnore: ["accounts/**"],
  timeout: 120_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:5173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    acceptDownloads: true,
  },
  outputDir: path.join(tmpDir, "results"),
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `${path.join(backendDir, "run_api.sh")}`,
      cwd: backendDir,
      env: { DATABASE_URL: dbUrl, PORT: "8000", RUN_WORKERS: "2", AUTH_MODE: "single_user", JOB_BACKEND: "inline" },
      url: "http://127.0.0.1:8000/api/v1/health",
      reuseExistingServer: false,
      timeout: 60_000,
      stdout: "ignore",
      stderr: "pipe",
    },
    {
      command: "npm run dev -- --host 127.0.0.1",
      cwd: frontendDir,
      url: "http://127.0.0.1:5173/api/v1/health",
      reuseExistingServer: false,
      timeout: 60_000,
      stdout: "ignore",
      stderr: "pipe",
    },
  ],
});
