/**
 * `/api/v1/auth/*` calls (PHASE2B 4.5). Separate from `authFetch`: sign-in/sign-up must never trigger the
 * "session expired" banner or the CSRF retry; sign-out and change-password send the token explicitly.
 */
import { API_BASE, ApiError, looksLikeProxyFailure, networkError } from "../api/client";
import { FETCH_CREDENTIALS, authHeaders, onAuthError } from "./authFetch";
import type { ChangePasswordRequest, SessionInfo, SignInRequest, SignUpRequest } from "./types";

async function call<T>(path: string, method: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json", ...authHeaders(method) };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/auth${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: FETCH_CREDENTIALS,
      signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw networkError();
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let parsed: unknown;
  try {
    parsed = text ? JSON.parse(text) : undefined;
  } catch {
    parsed = text;
  }
  if (!res.ok) {
    const e = (parsed as { error?: { code?: string; message?: string; details?: Record<string, unknown> } } | undefined)?.error;
    if (e && typeof e.code === "string") throw new ApiError(res.status, e.code, e.message ?? "", e.details ?? {});
    if (looksLikeProxyFailure(res.status, text)) throw networkError(res.status);
    throw new ApiError(res.status, `HTTP_${res.status}`, res.statusText || "Request failed");
  }
  return parsed as T;
}

export const fetchSession = (signal?: AbortSignal) => call<SessionInfo>("/session", "GET", undefined, signal);
export const postSignIn = (body: SignInRequest) => call<SessionInfo>("/sign-in", "POST", body);
export const postSignUp = (body: SignUpRequest) => call<SessionInfo>("/sign-up", "POST", body);
export const postSignOut = () => call<void>("/sign-out", "POST");

export async function postChangePassword(body: ChangePasswordRequest): Promise<SessionInfo> {
  try {
    return await call<SessionInfo>("/change-password", "POST", body);
  } catch (err) {
    // 401 here means the session itself ended (WRONG_PASSWORD is a 422 on purpose).
    if (err instanceof ApiError) onAuthError(err.status, err.code);
    throw err;
  }
}

/** Plain-language messages for the auth error codes (PHASE2B 4.5); `null` = use the server message. */
export function authErrorMessage(err: unknown): string | null {
  if (!(err instanceof ApiError)) return null;
  switch (err.code) {
    case "INVALID_CREDENTIALS":
      return "The email or password is not correct.";
    case "EMAIL_TAKEN":
      return "An account with this email already exists. Sign in instead.";
    case "SIGNUP_DISABLED":
      return "New accounts cannot be created on this server. Ask your administrator for an account.";
    case "WRONG_PASSWORD":
      return "Your current password is not correct.";
    case "RATE_LIMITED": {
      const s = Number(err.details.retry_after_seconds);
      const wait = Number.isFinite(s) && s > 0 ? (s >= 90 ? `${Math.ceil(s / 60)} minutes` : `${Math.ceil(s)} seconds`) : "a few minutes";
      return `Too many attempts. Please wait ${wait} and try again.`;
    }
    case "CSRF_FAILED":
      return "Your session could not be verified. Reload the page and try again.";
    case "WEAK_PASSWORD":
      return weakPasswordMessage(err.details.reasons);
    default:
      return null;
  }
}

const WEAK_TEXT: Record<string, string> = {
  too_short: "use at least 10 characters",
  too_long: "use at most 256 characters",
  common: "this password is too common, choose something less guessable",
  same_as_email: "do not use your email address as the password",
};

export function weakPasswordMessage(reasons: unknown): string {
  const list = Array.isArray(reasons) ? reasons.map((r) => WEAK_TEXT[String(r)]).filter(Boolean) : [];
  if (!list.length) return "Please choose a stronger password.";
  const text = list.join("; ");
  return `Please choose a stronger password: ${text}.`;
}
