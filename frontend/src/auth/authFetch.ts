/**
 * Request hooks shared by both API clients (PHASE2B 4.4, 4.10).
 *
 * - The CSRF token lives in memory only (never in storage) and is sent as `X-CSRF-Token` on every unsafe
 *   method once known. In single_user mode the server returns no token, so no header is ever sent.
 * - 401 `AUTH_REQUIRED` -> the registered handler marks the session expired (banner).
 * - 403 `CSRF_FAILED` -> refresh the session once (new token) and retry the request once.
 *
 * This module imports nothing from the API clients (they import it), so there is no import cycle.
 */

const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"]);

let csrfToken: string | null = null;

export interface AuthHandlers {
  /** A protected request answered 401 AUTH_REQUIRED. */
  onAuthRequired(): void;
  /**
   * Re-read `GET /auth/session` after a 403 CSRF_FAILED. Resolves true when the request may be retried: the same
   * user is still signed in (with a fresh token). False when signed out or a *different* user is now signed in
   * (another tab), so a write is never replayed as someone else.
   */
  refreshForRetry(): Promise<boolean>;
}

let handlers: AuthHandlers | null = null;

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

export function getCsrfToken(): string | null {
  return csrfToken;
}

/** Installed by `AuthProvider`; returns an uninstall function. */
export function registerAuthHandlers(h: AuthHandlers): () => void {
  handlers = h;
  return () => {
    if (handlers === h) handlers = null;
  };
}

export function isUnsafeMethod(method: string | undefined): boolean {
  return UNSAFE.has((method ?? "GET").toUpperCase());
}

/** Extra headers for one request: `X-CSRF-Token` on unsafe methods when a token is known. */
export function authHeaders(method: string | undefined): Record<string, string> {
  return csrfToken && isUnsafeMethod(method) ? { "X-CSRF-Token": csrfToken } : {};
}

/** Called for every error response of a protected endpoint. */
export function onAuthError(status: number, code: string | null): void {
  if (status === 401 && code === "AUTH_REQUIRED") handlers?.onAuthRequired();
}

/** All requests are same-origin (Vite proxy / nginx); cookies are sent explicitly. */
export const FETCH_CREDENTIALS: RequestCredentials = "same-origin";

async function errorCode(res: Response): Promise<string | null> {
  try {
    const body = (await res.clone().json()) as { error?: { code?: unknown } };
    return typeof body?.error?.code === "string" ? body.error.code : null;
  } catch {
    return null;
  }
}

/**
 * `fetch` with the auth hooks: adds the CSRF header and cookies, retries once after a CSRF refresh, and reports
 * 401 AUTH_REQUIRED. Network errors and aborts are thrown unchanged (the callers map them).
 */
export async function authFetch(url: string, init: RequestInit = {}): Promise<Response> {
  const send = () => {
    const headers = { ...(init.headers as Record<string, string> | undefined), ...authHeaders(init.method) };
    return fetch(url, { ...init, headers, credentials: FETCH_CREDENTIALS });
  };
  let res = await send();
  if (res.status === 403 && handlers && (await errorCode(res)) === "CSRF_FAILED") {
    let retry = false;
    try {
      retry = await handlers.refreshForRetry();
    } catch {
      retry = false; // refresh failed (network): report the original 403
    }
    if (!retry) return res;
    res = await send();
  }
  if (res.status === 401) onAuthError(401, await errorCode(res));
  return res;
}
