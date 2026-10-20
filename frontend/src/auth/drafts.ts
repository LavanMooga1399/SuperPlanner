/**
 * Browser-side intake drafts (`sessionStorage["sp.intake.*"]`) belong to the signed-in user (PHASE2B 4.8, 4.10):
 * they are cleared on sign-out and when a different user signs in in the same tab.
 */

export const INTAKE_PREFIX = "sp.intake.";
/** Id of the user the drafts in this tab belong to (not prefixed `sp.intake.`, so it survives clearing). */
const OWNER_KEY = "sp.auth.user";
/** Window event the intake provider listens to: stop persisting the in-memory draft. */
export const DRAFTS_CLEARED_EVENT = "sp:intake-drafts-cleared";

export function clearIntakeDrafts(): void {
  try {
    const keys: string[] = [];
    for (let i = 0; i < window.sessionStorage.length; i++) {
      const k = window.sessionStorage.key(i);
      if (k && k.startsWith(INTAKE_PREFIX)) keys.push(k);
    }
    for (const k of keys) window.sessionStorage.removeItem(k);
  } catch {
    /* storage unavailable */
  }
  window.dispatchEvent(new Event(DRAFTS_CLEARED_EVENT));
}

/** Record who is signed in; clears the drafts when it is someone else than before. */
export function noteSignedInUser(userId: string): void {
  try {
    const prev = window.sessionStorage.getItem(OWNER_KEY);
    if (prev !== null && prev !== userId) clearIntakeDrafts();
    window.sessionStorage.setItem(OWNER_KEY, userId);
  } catch {
    /* storage unavailable */
  }
}

/** Sign-out: drafts go, and the next user starts clean. */
export function forgetSignedInUser(): void {
  clearIntakeDrafts();
  try {
    window.sessionStorage.removeItem(OWNER_KEY);
  } catch {
    /* ignore */
  }
}
