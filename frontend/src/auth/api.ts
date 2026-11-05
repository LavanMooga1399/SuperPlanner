/**
 * `/api/v1/auth/*` calls (PHASE2B 4.5). Separate from `authFetch`: sign-in/sign-up must never trigger the
 * "session expired" banner or the CSRF retry; sign-out and change-password send the token explicitly.
 */
import { API_BASE, ApiError, looksLikeProxyFailure, networkError } from "../api/client";
import { FETCH_CREDENTIALS, authHeaders, onAuthError } from "./authFetch";
import type { AuthConfig, PendingLogin, RecoveryCodes, TotpSetup, TotpStatus } from "../mfg/api/typesM5";
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

// ---------------------------------------------------------------- M5 3.1-3.2: SSO and TOTP
export const fetchAuthConfig = (signal?: AbortSignal) => call<AuthConfig>("/config", "GET", undefined, signal);
/** Full-page navigation (not fetch): the server redirects to the identity provider. */
export const oidcLoginUrl = (next: string) => `${API_BASE}/auth/oidc/login?next=${encodeURIComponent(next)}`;
export const postLoginTotp = (body: { pending_token: string; code?: string; recovery_code?: string }) => call<SessionInfo>("/login/totp", "POST", body);
export const fetchTotpStatus = (signal?: AbortSignal) => call<TotpStatus>("/totp", "GET", undefined, signal);
/** `pending_token` when the organisation forces setup during sign-in */
export const postTotpSetup = (pendingToken?: string) => call<TotpSetup>("/totp/setup", "POST", pendingToken ? { pending_token: pendingToken } : {});
export const postTotpEnable = (code: string, pendingToken?: string) =>
  call<RecoveryCodes & Partial<SessionInfo>>("/totp/enable", "POST", pendingToken ? { code, pending_token: pendingToken } : { code });
export const postTotpDisable = (code: string) => call<void>("/totp/disable", "POST", { code });
export const postRecoveryCodes = (code: string) => call<RecoveryCodes>("/totp/recovery-codes", "POST", { code });

/** A sign-in answer that asks for a second factor: 200 with `pending_login`, or an `AUTH_2FA_REQUIRED` error. */
export function pendingLoginOf(x: unknown): PendingLogin | null {
  if (x instanceof ApiError) {
    if (x.code !== "AUTH_2FA_REQUIRED") return null;
    const d = x.details as Partial<PendingLogin> & { setup_required?: boolean };
    return d.pending_token ? { pending_token: d.pending_token, method: d.method ?? (d.setup_required ? "setup" : "totp"), expires_at: d.expires_at ?? null } : null;
  }
  const p = (x as { pending_login?: PendingLogin } | null)?.pending_login;
  return p?.pending_token ? p : null;
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
    case "AUTH_SSO_REQUIRED":
      return "Your organisation signs in with single sign-on. Use the sign-in button for your company account.";
    case "AUTH_SSO_NOT_ALLOWED":
      return "Your company account is not allowed to use this server. Ask your administrator to add you.";
    case "AUTH_TOTP_INVALID":
      return "That code is not correct or has expired. Enter the current 6-digit code from your authenticator app.";
    case "AUTH_2FA_REQUIRED":
      return "Enter the code from your authenticator app to finish signing in.";
    case "AUTH_PENDING_EXPIRED":
      return "Signing in took too long. Enter your email and password again.";
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
