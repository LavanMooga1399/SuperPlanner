/**
 * The `next` parameter of `/sign-in` and `/sign-up` (PHASE2B 4.10, Q4-4). Only same-origin relative paths are
 * accepted - anything else (absolute URLs, `//host`, `/\host`, schemes, control characters) becomes `/`,
 * so the parameter cannot be used as an open redirect.
 */

const AUTH_PAGES = /^\/(sign-in|sign-up)(?:[/?#]|$)/;

export function safeNext(raw: string | null | undefined): string {
  if (!raw) return "/";
  // eslint-disable-next-line no-control-regex
  if (!raw.startsWith("/") || raw.startsWith("//") || raw.startsWith("/\\") || /[\u0000-\u001f\u007f\\]/.test(raw)) return "/";
  try {
    const u = new URL(raw, window.location.origin);
    if (u.origin !== window.location.origin) return "/";
    const path = u.pathname + u.search + u.hash;
    return AUTH_PAGES.test(path) ? "/" : path;
  } catch {
    return "/";
  }
}

/** `/sign-in?next=<current path+search>` for the given location. */
export function signInHref(pathname: string, search = "", page: "sign-in" | "sign-up" = "sign-in"): string {
  const next = safeNext(pathname + search);
  return next === "/" ? `/${page}` : `/${page}?next=${encodeURIComponent(next)}`;
}
