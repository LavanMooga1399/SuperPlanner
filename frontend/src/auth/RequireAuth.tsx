/**
 * Guard around the app's route tree (PHASE2B 4.10): accounts + anonymous -> `/sign-in?next=<path+search>`;
 * loading -> spinner; single_user -> the pages as before. An *expired* session keeps the page (the banner offers
 * to sign in again) so unsaved work on screen is not thrown away.
 */
import { Navigate, Outlet, useLocation } from "react-router";
import { useAuth } from "./AuthContext";
import { signInHref } from "./nextPath";
import { AuthLoading } from "./SignInPage";

export function RequireAuth() {
  const { mode, status, signedOut } = useAuth();
  const loc = useLocation();
  if (status === "loading") return <AuthLoading />;
  if (mode === "accounts" && status === "anonymous") {
    return <Navigate to={signedOut ? "/sign-in" : signInHref(loc.pathname, loc.search)} replace />;
  }
  return <Outlet />;
}
