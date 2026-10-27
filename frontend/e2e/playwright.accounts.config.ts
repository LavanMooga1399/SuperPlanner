/**
 * Accounts-mode e2e (PHASE2B 4.10, R13): its own API on :8001 (AUTH_MODE=accounts, its own fresh PostgreSQL
 * database, created + migrated by backend/scripts/run_e2e_api.sh and dropped by global-teardown.ts) and its
 * own Vite on :5174 proxying to it. The browser's Origin is the Vite origin (`changeOrigin` rewrites only Host),
 * so PUBLIC_BASE_URL / CORS_ORIGINS must name it or every sign-in fails the Origin check with 403.
 * Run: `npm run e2e:accounts`. Specs live in `e2e/accounts/`.
 */
import { defineConfig, devices } from "@playwright/test";
import * as os from "node:os";
import * as path from "node:path";
import * as fs from "node:fs";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));

// Loaded by the runner and by every worker: share temp dir and database name through the env.
process.env.SP_E2E_ACCOUNTS_TMP ??= fs.mkdtempSync(path.join(os.tmpdir(), "sp-e2e-accounts-"));
process.env.SP_E2E_DB ??= `sp_e2e_acc_${Date.now()}_${process.pid}`;
const tmpDir = process.env.SP_E2E_ACCOUNTS_TMP;
const dbName = process.env.SP_E2E_DB;
const backendDir = path.resolve(here, "../../backend");
const frontendDir = path.resolve(here, "..");

const API_PORT = "8001";
const UI_ORIGIN = "http://127.0.0.1:5174";

process.env.PLAYWRIGHT_BROWSERS_PATH ??= "/opt/pw-browsers";

export default defineConfig({
  testDir: "./accounts",
  testMatch: /.*\.spec\.ts$/,
  timeout: 120_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: UI_ORIGIN,
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
      env: {
        SP_E2E_DB: dbName,
        APP_ENV: "development",
        PORT: API_PORT,
        RUN_WORKERS: "2",
        AUTH_MODE: "accounts",
        JOB_BACKEND: "queue",
        WORKER_POLL_SECONDS: "0.2",
        JOB_CANCEL_POLL_SECONDS: "0.2",
        WORKER_SHUTDOWN_GRACE_SECONDS: "2",
        COOKIE_SECURE: "false",
        AUTH_SIGNIN_LIMIT_PER_IP: "1000",
        AUTH_SIGNUP_LIMIT_PER_IP: "1000",
        PUBLIC_BASE_URL: UI_ORIGIN,
        CORS_ORIGINS: UI_ORIGIN,
        // Test-only fast argon2 profile (refused outside APP_ENV=development); keeps sign-up/sign-in quick.
        PASSWORD_HASH_PROFILE: "fast",
      },
      url: `http://127.0.0.1:${API_PORT}/api/v1/health`,
      reuseExistingServer: false,
      timeout: 60_000,
      stdout: "ignore",
      stderr: "pipe",
    },
    {
      command: "npm run dev -- --host 127.0.0.1 --port 5174",
      cwd: frontendDir,
      env: { SP_API_TARGET: `http://127.0.0.1:${API_PORT}` },
      url: `${UI_ORIGIN}/api/v1/health`,
      reuseExistingServer: false,
      timeout: 60_000,
      stdout: "ignore",
      stderr: "pipe",
    },
  ],
});
