/**
 * Playwright global teardown (both e2e configs): drop the per-run PostgreSQL database that
 * backend/scripts/run_e2e_api.sh created (name in SP_E2E_DB). Best effort: a failure is logged, never fatal.
 */
import { execFileSync } from "node:child_process";
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const backendDir = path.resolve(here, "../../backend");

export default async function globalTeardown(): Promise<void> {
  const name = process.env.SP_E2E_DB;
  if (!name) return;
  const venv = path.join(backendDir, ".venv", "bin", "python");
  const py = fs.existsSync(venv) ? venv : "python3";
  try {
    execFileSync(py, [path.join(backendDir, "scripts", "e2e_db.py"), "drop", name], {
      cwd: backendDir,
      stdio: ["ignore", "ignore", "pipe"],
      timeout: 60_000,
    });
  } catch (err) {
    console.warn(`e2e teardown: could not drop database ${name}: ${String(err)}`);
  }
}
