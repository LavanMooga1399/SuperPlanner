/**
 * Shared helpers of the demo recorder (record-demo.mjs): start the API + dev server on a fresh database, the
 * caption bar / title cards injected into the page, paced mouse movement and small API helpers.
 */
import { spawn, execFileSync } from "node:child_process";
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
export const frontendDir = path.resolve(here, "..");
export const backendDir = path.resolve(here, "../../backend");
export const API_PORT = Number(process.env.DEMO_API_PORT ?? 8010);
export const WEB_PORT = Number(process.env.DEMO_WEB_PORT ?? 5183);
export const BASE = `http://127.0.0.1:${WEB_PORT}`;
export const API = `http://127.0.0.1:${API_PORT}/api/v1`;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function waitHttp(url, timeoutMs = 90_000) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    try {
      const r = await fetch(url);
      if (r.ok) return;
    } catch {
      /* not up yet */
    }
    await sleep(500);
  }
  throw new Error(`timed out waiting for ${url}`);
}

/** Start API (fresh database `sp_demo_<ts>`, APP_ENV=development, ASSISTANT_AI_DEMO=true) and the Vite dev server. */
export async function startServers({ log = false, accounts = false } = {}) {
  const db = process.env.SP_E2E_DB ?? `sp_demo_${Date.now()}`;
  const procs = [];
  const out = log ? "inherit" : "ignore";
  const api = spawn(path.join(backendDir, "scripts", "run_e2e_api.sh"), [], {
    cwd: backendDir,
    env: {
      ...process.env,
      SP_E2E_DB: db,
      APP_ENV: "development",
      PORT: String(API_PORT),
      RUN_WORKERS: "2",
      AUTH_MODE: accounts ? "accounts" : "single_user",
      ...(accounts
        ? {
            // accounts mode (signatures need a person with a password); development-only settings as in
            // e2e/playwright.accounts.config.ts, with a throwaway signing/TOTP key for this run
            COOKIE_SECURE: "false",
            AUTH_SIGNIN_LIMIT_PER_IP: "1000",
            AUTH_SIGNUP_LIMIT_PER_IP: "1000",
            PUBLIC_BASE_URL: `http://127.0.0.1:${WEB_PORT}`,
            CORS_ORIGINS: `http://127.0.0.1:${WEB_PORT}`,
            PASSWORD_HASH_PROFILE: "fast",
            SECRETS_KEY: Buffer.from(Array.from({ length: 32 }, (_, i) => (i * 7 + 3) % 256)).toString("base64").replace(/\+/g, "-").replace(/\//g, "_"),
          }
        : {}),
      JOB_BACKEND: "queue",
      WORKER_POLL_SECONDS: "0.2",
      ASSISTANT_AI_DEMO: "true",
    },
    stdio: ["ignore", out, out],
    detached: true,
  });
  procs.push(api);
  const web = spawn("npm", ["run", "dev", "--", "--host", "127.0.0.1", "--port", String(WEB_PORT), "--strictPort"], {
    cwd: frontendDir,
    env: { ...process.env, SP_API_TARGET: `http://127.0.0.1:${API_PORT}` },
    stdio: ["ignore", out, out],
    detached: true,
  });
  procs.push(web);
  const stop = () => {
    for (const p of procs) {
      try {
        process.kill(-p.pid, "SIGTERM");
      } catch {
        /* gone */
      }
    }
    try {
      const venv = path.join(backendDir, ".venv", "bin", "python");
      execFileSync(fs.existsSync(venv) ? venv : "python3", [path.join(backendDir, "scripts", "e2e_db.py"), "drop", db], { cwd: backendDir, stdio: "ignore", timeout: 60_000 });
    } catch {
      /* best effort */
    }
  };
  process.on("exit", stop);
  process.on("SIGINT", () => {
    stop();
    process.exit(130);
  });
  await waitHttp(`${API}/health`);
  await waitHttp(`${BASE}/api/v1/health`);
  return { stop, db };
}

// ---------------------------------------------------------------- accounts-mode session (cookie + CSRF + workspace)

export class Session {
  constructor() {
    this.cookies = new Map();
    this.csrf = "";
    this.workspace = null;
    this.userId = null;
  }

  async raw(method, url, body, headers = {}) {
    const r = await fetch(url, {
      method,
      headers: {
        "Content-Type": "application/json",
        Cookie: [...this.cookies].map(([k, v]) => `${k}=${v}`).join("; "),
        ...(this.csrf ? { "X-CSRF-Token": this.csrf } : {}),
        ...headers,
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    for (const c of r.headers.getSetCookie?.() ?? []) {
      const [kv] = c.split(";");
      const i = kv.indexOf("=");
      this.cookies.set(kv.slice(0, i).trim(), kv.slice(i + 1).trim());
    }
    const text = await r.text();
    if (!r.ok) throw new Error(`${method} ${url} -> ${r.status} ${text.slice(0, 400)}`);
    const json = text ? JSON.parse(text) : null;
    if (json && typeof json === "object" && json.csrf_token) this.csrf = json.csrf_token;
    return json;
  }

  async signUp(email, password, displayName) {
    await this.raw("POST", `${API}/auth/sign-up`, { email, password, display_name: displayName });
    const s = await this.raw("GET", `${API}/auth/session`);
    this.userId = s.user.id;
    if (s.csrf_token) this.csrf = s.csrf_token;
    return s;
  }

  mfg(method, p, body, headers = {}) {
    return this.raw(method, `${API}/mfg${p}`, body, { ...(this.workspace ? { "X-SP-Workspace": this.workspace } : {}), ...headers });
  }
}

/** The session `api()` uses (accounts mode); null = single-user mode (no login). */
let current = null;
export function useSession(s) {
  current = s;
}

// ---------------------------------------------------------------- API helpers

export async function api(method, p, body, headers = {}) {
  if (current) return current.mfg(method, p, body, headers);
  const r = await fetch(`${API}/mfg${p}`, {
    method,
    headers: { "Content-Type": "application/json", ...headers },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await r.text();
  if (!r.ok) throw new Error(`${method} ${p} -> ${r.status} ${text.slice(0, 400)}`);
  return text ? JSON.parse(text) : null;
}

export async function waitRun(kind, id, timeoutMs = 180_000) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    const run = await api("GET", `/${kind}/runs/${id}`);
    if (["completed", "failed", "cancelled"].includes(run.status)) {
      if (run.status !== "completed") throw new Error(`${kind} run ${id} ${run.status}`);
      return run;
    }
    await sleep(700);
  }
  throw new Error(`${kind} run ${id} timed out`);
}

// ---------------------------------------------------------------- captions and cards (injected DOM)

/** Init script: a caption bar that survives reloads (text kept in sessionStorage), styled with the app tokens. */
export const CAPTION_INIT = `(() => {
  const KEY = "sp-demo-caption";
  const css = \`
    #sp-demo-caption { position: fixed; left: 50%; bottom: 28px; transform: translateX(-50%); z-index: 2147483000;
      max-width: min(1100px, 86vw); padding: 12px 22px; border-radius: var(--radius-lg, 8px);
      background: rgba(22, 27, 38, 0.92); color: #fff; font: 500 20px/1.35 var(--font, Inter, system-ui, sans-serif);
      box-shadow: 0 6px 24px rgba(0,0,0,.25); text-align: center; pointer-events: none; letter-spacing: .1px;
      border-left: 4px solid var(--accent, #1f5fbf); transition: opacity .35s ease; }
    #sp-demo-caption[data-empty="true"] { opacity: 0; }
    #sp-demo-card { position: fixed; inset: 0; z-index: 2147483001; display: flex; align-items: center; justify-content: center;
      background: var(--bg, #f3f4f6); font-family: var(--font, Inter, system-ui, sans-serif); transition: opacity .5s ease; }
    #sp-demo-card .box { max-width: 1000px; padding: 56px 64px; background: var(--surface, #fff); border-radius: 12px;
      border-top: 6px solid var(--accent, #1f5fbf); box-shadow: 0 10px 40px rgba(0,0,0,.08); }
    #sp-demo-card h1 { margin: 0 0 14px; font-size: 44px; font-weight: 650; color: var(--text, #161b26); letter-spacing: -.5px; }
    #sp-demo-card p { margin: 6px 0; font-size: 24px; color: var(--text-muted, #4d5666); line-height: 1.4; }
    #sp-demo-card p.small { margin-top: 26px; font-size: 17px; color: var(--text-faint, #687183); }
    #sp-demo-cursor { position: fixed; z-index: 2147483002; width: 22px; height: 22px; margin: -11px 0 0 -11px; border-radius: 50%;
      background: rgba(31, 95, 191, .25); border: 2px solid rgba(31, 95, 191, .85); pointer-events: none; transition: transform .12s; }
    #sp-demo-cursor.down { transform: scale(.7); background: rgba(31, 95, 191, .5); }\`;
  const ensure = () => {
    if (!document.body) return;
    if (!document.getElementById("sp-demo-style")) {
      const st = document.createElement("style");
      st.id = "sp-demo-style";
      st.textContent = css;
      document.head.appendChild(st);
    }
    let el = document.getElementById("sp-demo-caption");
    if (!el) {
      el = document.createElement("div");
      el.id = "sp-demo-caption";
      el.setAttribute("aria-hidden", "true");
      document.body.appendChild(el);
    }
    const t = sessionStorage.getItem(KEY) || "";
    if (el.textContent !== t) el.textContent = t;
    el.dataset.empty = t ? "false" : "true";
    // never cover an open dialog or drawer: move the bar into the wider free strip beside it
    const open = [...document.querySelectorAll('[role="dialog"], [data-testid="asst-panel"]')]
      .map((d) => d.getBoundingClientRect()).filter((r) => r.width > 0 && r.height > 0)
      .sort((a, b) => b.width * b.height - a.width * a.height)[0];
    let pos = "";
    if (open) {
      const left = open.left, right = window.innerWidth - open.right;
      const gap = Math.max(left, right);
      if (gap >= 170) {
        const cx = left >= right ? left / 2 : open.right + right / 2;
        pos = "left:" + cx + "px;top:50%;bottom:auto;transform:translate(-50%,-50%);max-width:" + (gap - 24) + "px;font-size:" + (gap < 260 ? 15 : 18) + "px;padding:10px 14px";
      } else if (open.bottom < window.innerHeight - 110) {
        pos = "";                                  // the default bottom bar is below the dialog
      } else {
        pos = "top:auto;bottom:4px;font-size:16px;padding:6px 14px;opacity:.95";
      }
    }
    if (el.dataset.pos !== pos) {
      el.dataset.pos = pos;
      el.style.cssText = pos;
    }
    let cur = document.getElementById("sp-demo-cursor");
    if (!cur) {
      cur = document.createElement("div");
      cur.id = "sp-demo-cursor";
      cur.style.left = (window.__spX ?? -50) + "px";
      cur.style.top = (window.__spY ?? -50) + "px";
      document.body.appendChild(cur);
    }
  };
  window.__spCaption = (t) => { sessionStorage.setItem(KEY, t || ""); ensure(); };
  // a title card kept across page loads (sp-demo-card-html), so a full reload never shows a blank frame
  const ensureCard = () => {
    const html = sessionStorage.getItem("sp-demo-card-html");
    if (!html || !document.body || document.getElementById("sp-demo-card")) return;
    const d = document.createElement("div");
    d.id = "sp-demo-card";
    d.innerHTML = html;
    document.body.appendChild(d);
  };
  window.__spEnsureCard = ensureCard;
  document.addEventListener("mousemove", (e) => {
    const c = document.getElementById("sp-demo-cursor");
    window.__spX = e.clientX; window.__spY = e.clientY;
    if (c) { c.style.left = e.clientX + "px"; c.style.top = e.clientY + "px"; }
  }, true);
  document.addEventListener("mousedown", () => document.getElementById("sp-demo-cursor")?.classList.add("down"), true);
  document.addEventListener("mouseup", () => document.getElementById("sp-demo-cursor")?.classList.remove("down"), true);
  if (window.top === window) {
    new MutationObserver(() => { ensure(); ensureCard(); }).observe(document.documentElement, { childList: true, subtree: true });
    document.addEventListener("DOMContentLoaded", ensure);
    setInterval(ensure, 200);
  }
})();`;

export async function caption(page, text) {
  await page.evaluate((t) => window.__spCaption?.(t), text);
}

/** Kept for older scene code: the caption bar now moves beside open dialogs by itself (CAPTION_INIT). */
export async function captionAtTop() {}

export async function card(page, title, lines, small, holdMs) {
  await page.evaluate((init) => {
    if (!window.__spCaption) (0, eval)(init);
    window.__spCaption("");
  }, CAPTION_INIT);
  await page.evaluate(
    ([t, ls, sm]) => {
      document.getElementById("sp-demo-card")?.remove();
      const d = document.createElement("div");
      d.id = "sp-demo-card";
      const box = document.createElement("div");
      box.className = "box";
      const h = document.createElement("h1");
      h.textContent = t;
      box.appendChild(h);
      for (const l of ls) {
        const p = document.createElement("p");
        p.textContent = l;
        box.appendChild(p);
      }
      if (sm) {
        const p = document.createElement("p");
        p.className = "small";
        p.textContent = sm;
        box.appendChild(p);
      }
      d.appendChild(box);
      document.body.appendChild(d);
      sessionStorage.setItem("sp-demo-card-html", d.innerHTML);
    },
    [title, lines, small],
  );
  await page.waitForTimeout(holdMs);
}

export async function uncard(page) {
  await page.evaluate(() => {
    sessionStorage.removeItem("sp-demo-card-html");
    const d = document.getElementById("sp-demo-card");
    if (d) {
      d.style.opacity = "0";
      setTimeout(() => d.remove(), 600);
    }
  });
  await page.waitForTimeout(700);
}

// ---------------------------------------------------------------- paced pointer

let mx = 200;
let my = 200;

/** Glide the mouse to the centre of a locator (slow, eased), optionally click. */
export async function glide(page, locator, { click = false, pause = 350, steps = 28, optional = false, scroll = true } = {}) {
  try {
    await locator.first().waitFor({ state: "visible", timeout: optional ? 4000 : 20_000 });
  } catch (e) {
    if (optional) {
      console.warn(`  (skipped: ${locator} not visible)`);
      return false;
    }
    throw e;
  }
  locator = locator.first();
  if (scroll) await locator.scrollIntoViewIfNeeded().catch(() => undefined);
  const box = await locator.boundingBox();
  if (!box) throw new Error(`no box for ${locator}`);
  const tx = box.x + box.width / 2;
  const ty = box.y + Math.min(box.height / 2, 18);
  for (let i = 1; i <= steps; i++) {
    const k = i / steps;
    const e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
    await page.mouse.move(mx + (tx - mx) * e, my + (ty - my) * e);
    await page.waitForTimeout(12);
  }
  mx = tx;
  my = ty;
  await page.waitForTimeout(pause);
  if (click) {
    await page.mouse.down();
    await page.waitForTimeout(90);
    await page.mouse.up();
  }
  return true;
}

export async function settle(page, ms = 1200) {
  await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => undefined);
  // no visible spinners
  await page
    .waitForFunction(() => ![...document.querySelectorAll(".spinner, [aria-busy='true'], .skel, .skel-row, .skel-rows, .skel-page, .vt-skel-row")].some((e) => e.getClientRects().length), null, { timeout: 20_000 })
    .catch(() => undefined);
  await page.waitForTimeout(ms);
}

export { sleep };
