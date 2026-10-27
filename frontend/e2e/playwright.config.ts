import { defineConfig, devices } from "@playwright/test";
import * as os from "node:os";
import * as path from "node:path";
import * as fs from "node:fs";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));

// A fresh PostgreSQL database per run on the dev/test cluster (backend/scripts/pg_dev_cluster.sh; admin URL:
// SP_E2E_PG_URL / SP_TEST_PG_URL): created and migrated by backend/scripts/run_e2e_api.sh, dropped by
// global-teardown.ts. The config is loaded by the runner and by every worker; share name and temp dir via the env.
process.env.SP_E2E_TMP ??= fs.mkdtempSync(path.join(os.tmpdir(), "sp-e2e-"));
process.env.SP_E2E_DB ??= `sp_e2e_${Date.now()}_${process.pid}`;
const tmpDir = process.env.SP_E2E_TMP;
const dbName = process.env.SP_E2E_DB;
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
  globalTeardown: "./global-teardown.ts",
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `${path.join(backendDir, "scripts", "run_e2e_api.sh")}`,
      cwd: backendDir,
      // PostgreSQL queue backend with embedded worker threads (APP_ENV=development default: WORKER_EMBEDDED=auto).
      env: {
        SP_E2E_DB: dbName,
        APP_ENV: "development",
        PORT: "8000",
        RUN_WORKERS: "2",
        AUTH_MODE: "single_user",
        JOB_BACKEND: "queue",
        WORKER_POLL_SECONDS: "0.2",
        JOB_CANCEL_POLL_SECONDS: "0.2",
        WORKER_SHUTDOWN_GRACE_SECONDS: "2",
      },
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
