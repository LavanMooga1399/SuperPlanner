/**
 * Who is signed in (PHASE2B 4.10).
 *
 * `AuthProvider` reads `GET /auth/session` once at boot. In single_user mode (or when that request fails with a
 * network error or 404, e.g. an older backend) the app renders exactly as before: no login, no menu, no CSRF
 * header. In accounts mode it keeps the user and the CSRF token (memory only), reports `expired` after a 401
 * from any protected request, and clears browser intake drafts on sign-out and when the user changes.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Outlet, useNavigate } from "react-router";
import { ApiError, isNetworkError } from "../api/client";
import { fetchSession, postChangePassword, postSignIn, postSignOut, postSignUp } from "./api";
import { registerAuthHandlers, setCsrfToken } from "./authFetch";
import { forgetSignedInUser, noteSignedInUser } from "./drafts";
import type { AuthMode, AuthUser, ChangePasswordRequest, SessionInfo, SignInRequest, SignUpRequest } from "./types";

export type AuthStatus = "loading" | "anonymous" | "authenticated";

export interface AuthState {
  mode: AuthMode;
  user: AuthUser | null;
  csrfToken: string | null;
  status: AuthStatus;
  /** A protected request answered 401 while we thought we were signed in. */
  expired: boolean;
  signupEnabled: boolean;
  expiresAt: string | null;
  /** True when the session endpoint could not be read and single_user was assumed. */
  assumed: boolean;
  /** Set by `signOut` so the guard goes to plain `/sign-in` (no `next` back to the page just left). */
  signedOut: boolean;
}

export interface AuthApi extends AuthState {
  signIn(body: SignInRequest): Promise<SessionInfo>;
  signUp(body: SignUpRequest): Promise<SessionInfo>;
  signOut(): Promise<void>;
  changePassword(body: ChangePasswordRequest): Promise<SessionInfo>;
  refresh(): Promise<SessionInfo | null>;
  markExpired(): void;
}

const INITIAL: AuthState = {
  mode: "single_user",
  user: null,
  csrfToken: null,
  status: "loading",
  expired: false,
  signupEnabled: false,
  expiresAt: null,
  assumed: false,
  signedOut: false,
};

const ASSUMED_SINGLE_USER: AuthState = { ...INITIAL, status: "authenticated", assumed: true };

function fromSession(info: SessionInfo): AuthState {
  if (info.auth_mode !== "accounts") {
    return { ...INITIAL, mode: "single_user", user: info.user, status: "authenticated" };
  }
  const signedIn = info.authenticated && info.user !== null;
  return {
    mode: "accounts",
    user: signedIn ? info.user : null,
    csrfToken: signedIn ? info.csrf_token : null,
    status: signedIn ? "authenticated" : "anonymous",
    expired: false,
    signupEnabled: info.signup_enabled,
    expiresAt: signedIn ? info.expires_at : null,
    assumed: false,
    signedOut: false,
  };
}

/** A failed session read that means "no auth support here": render as single_user. */
function meansSingleUser(err: unknown): boolean {
  return isNetworkError(err) || (err instanceof ApiError && (err.status === 404 || err.status === 405));
}

const Ctx = createContext<AuthApi | null>(null);

/** The boot read of `GET /auth/session`, shared by every mount in this page load. */
let bootSession: Promise<SessionInfo> | null = null;

export function useAuth(): AuthApi {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth outside AuthProvider");
  return v;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  const [state, setState] = useState<AuthState>(INITIAL);
  const stateRef = useRef(state);

  /** Single place that changes the auth state, so the token store and the drafts owner always follow. */
  const apply = useCallback((next: AuthState) => {
    stateRef.current = next;
    setCsrfToken(next.mode === "accounts" ? next.csrfToken : null);
    if (next.mode === "accounts" && next.status === "authenticated" && next.user) noteSignedInUser(next.user.id);
    setState(next);
  }, []);

  const refresh = useCallback(async (): Promise<SessionInfo | null> => {
    try {
      const info = await fetchSession();
      apply(fromSession(info));
      return info;
    } catch (err) {
      if (meansSingleUser(err) && stateRef.current.status === "loading") apply(ASSUMED_SINGLE_USER);
      return null;
    }
  }, [apply]);

  // Boot: one GET /auth/session per page load (shared, so StrictMode's double effect does not send two).
  useEffect(() => {
    let alive = true;
    bootSession ??= fetchSession();
    bootSession
      .then((info) => alive && apply(fromSession(info)))
      .catch(() => {
        // 404 / network: an older or unreachable backend -> single_user. Any other error: still render;
        // a protected request answering 401 later re-reads the session (markExpired with `assumed`).
        if (alive) apply(ASSUMED_SINGLE_USER);
      });
    return () => {
      alive = false;
    };
  }, [apply]);

  const markExpired = useCallback(() => {
    const cur = stateRef.current;
    if (cur.mode === "accounts" && cur.status === "authenticated") {
      if (!cur.expired) apply({ ...cur, expired: true });
    } else if (cur.assumed) {
      // We guessed single_user at boot but the server wants a session: find out the real mode.
      void refresh();
    }
  }, [apply, refresh]);

  // Hooks used by both API clients (authFetch).
  useEffect(
    () =>
      registerAuthHandlers({
        onAuthRequired: markExpired,
        refreshForRetry: async () => {
          const before = stateRef.current.user?.id ?? null;
          const info = await fetchSession();
          const next = fromSession(info);
          const after = next.user?.id ?? null;
          if (before !== null && after !== null && before !== after) {
            // Another tab signed in as someone else: start over on the home page as that user.
            apply(next);
            void navigate("/", { replace: true });
            return false;
          }
          if (next.mode === "accounts" && next.status !== "authenticated") {
            // Signed out elsewhere: keep the page, show the expired banner.
            const cur = stateRef.current;
            apply({ ...cur, csrfToken: null, expired: cur.status === "authenticated" });
            return false;
          }
          apply(next);
          return true;
        },
      }),
    [apply, markExpired, navigate],
  );

  const signIn = useCallback(
    async (body: SignInRequest) => {
      const info = await postSignIn(body);
      apply(fromSession(info));
      return info;
    },
    [apply],
  );

  const signUp = useCallback(
    async (body: SignUpRequest) => {
      const info = await postSignUp(body);
      apply(fromSession(info));
      return info;
    },
    [apply],
  );

  const signOut = useCallback(async () => {
    try {
      await postSignOut();
    } catch {
      /* already signed out / unreachable: sign out locally anyway */
    }
    // Drafts first (the intake provider stops persisting on the event), then the state, then the page. The guard
    // also sends a signed-out user to plain /sign-in, so whichever navigation lands first, the result is the same.
    forgetSignedInUser();
    const cur = stateRef.current;
    apply({ ...cur, user: null, csrfToken: null, status: "anonymous", expired: false, expiresAt: null, signedOut: true });
    await navigate("/sign-in", { replace: true });
  }, [apply, navigate]);

  const changePassword = useCallback(
    async (body: ChangePasswordRequest) => {
      const info = await postChangePassword(body);
      apply(fromSession(info));
      return info;
    },
    [apply],
  );

  const value = useMemo<AuthApi>(
    () => ({ ...state, signIn, signUp, signOut, changePassword, refresh, markExpired }),
    [state, signIn, signUp, signOut, changePassword, refresh, markExpired],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

/** Root route element: the provider needs the router (navigate), so it sits inside it. */
export function AuthRoot() {
  return (
    <AuthProvider>
      <Outlet />
    </AuthProvider>
  );
}
