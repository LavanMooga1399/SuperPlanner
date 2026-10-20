/** Auth contract types (PHASE2B 4.5). */

export type AuthMode = "single_user" | "accounts";

export interface AuthUser {
  id: string;
  email: string | null;
  display_name: string | null;
  is_local: boolean;
  created_at: string;
}

/** `SessionInfo`: body of `GET /auth/session`, sign-in, sign-up and change-password. */
export interface SessionInfo {
  auth_mode: AuthMode;
  authenticated: boolean;
  user: AuthUser | null;
  csrf_token: string | null;
  expires_at: string | null;
  signup_enabled: boolean;
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
