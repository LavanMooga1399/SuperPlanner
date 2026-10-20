/** Shown at the top of `<main>` after a protected request answered 401 (PHASE2B 4.10, Q4-4). */
import { useLocation, useNavigate } from "react-router";
import { Banner } from "../components/Banner";
import { Icon } from "../components/Icon";
import { useAuth } from "./AuthContext";
import { signInHref } from "./nextPath";
import { SESSION_ENDED_MESSAGE } from "./types";

export function SessionExpiredBanner() {
  const { mode, expired } = useAuth();
  const loc = useLocation();
  const navigate = useNavigate();
  if (mode !== "accounts" || !expired) return null;
  if (/^\/(sign-in|sign-up)(\/|$)/.test(loc.pathname)) return null;
  return (
    <div className="mb">
      <Banner
        tone="warn"
        icon="lock"
        role="alert"
        testId="session-expired"
        title="Session ended"
        actions={
          <button
            type="button"
            className="btn primary sm"
            data-testid="session-expired-signin"
            onClick={() => void navigate(signInHref(loc.pathname, loc.search))}
          >
            <Icon name="arrow-right" /> Sign in again
          </button>
        }
      >
        {SESSION_ENDED_MESSAGE}
      </Banner>
    </div>
  );
}
