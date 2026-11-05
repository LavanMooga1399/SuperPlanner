/** Auth contract types (PHASE2B 4.5). */

export type AuthMode = "single_user" | "accounts";

export interface AuthUser {
  id: string;
  email: string | null;
  display_name: string | null;
  is_local: boolean;
  created_at: string;
  /** M5 3.2 */
  totp_enabled?: boolean;
  /** M5 3.1: the account signs in through the company identity provider */
  sso?: boolean;
}

/** `SessionInfo`: body of `GET /auth/session`, sign-in, sign-up and change-password. */
export interface SessionInfo {
  auth_mode: AuthMode;
  authenticated: boolean;
  user: AuthUser | null;
  csrf_token: string | null;
  expires_at: string | null;
  signup_enabled: boolean;
  /** M5 3.2: password accepted, a second factor is still needed (the session is not yet authenticated) */
  pending_login?: { pending_token: string; method: "totp" | "setup"; expires_at?: string | null } | null;
  /** M5 3.2: signed in, but the organisation requires 2FA and the account has none yet */
  totp_setup_required?: boolean;
}

export interface SignUpRequest {
  email: string;
  password: string;
  display_name?: string;
}

export interface SignInRequest {
  email: string;
  password: string;
}

export interface ChangePasswordRequest {
  current_password: string;
  new_password: string;
}

/** Shown when a protected request answers 401 AUTH_REQUIRED; also the API's own message. */
export const SESSION_ENDED_MESSAGE = "Your session has ended. Sign in again to continue.";
