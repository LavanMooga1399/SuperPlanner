/**
 * Top-bar account menu (PHASE2B 4.10), hidden in single_user mode. Menu-button pattern: Enter/Space/ArrowDown
 * open it and focus the first item, arrows move, Escape closes and returns focus, Tab or a click outside closes.
 */
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { Link } from "react-router";
import { Icon } from "../components/Icon";
import { useAuth } from "./AuthContext";
import "./auth.css";

function initials(label: string): string {
  const parts = label.replace(/@.*/, "").split(/[\s._-]+/).filter(Boolean);
  const s = (parts[0]?.[0] ?? "?") + (parts.length > 1 ? parts[parts.length - 1][0] : "");
  return s.toUpperCase();
}

function SignOutIcon() {
  return (
    <svg width={16} height={16} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M6 2.5H3.5a1 1 0 0 0-1 1v9a1 1 0 0 0 1 1H6M10.5 11l3-3-3-3M13.5 8H6" />
    </svg>
  );
}

export function AccountMenu() {
  const auth = useAuth();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const menuId = useId();

  const items = () => Array.from(listRef.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? []);

  useEffect(() => {
    if (!open) return;
    items()[0]?.focus();
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  if (auth.mode !== "accounts" || auth.status !== "authenticated" || !auth.user) return null;
  const user = auth.user;
  const label = user.display_name || user.email || "Account";

  const close = (refocus: boolean) => {
    setOpen(false);
    if (refocus) buttonRef.current?.focus();
  };

  const onButtonKey = (e: KeyboardEvent) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      setOpen(true);
    }
  };

  const onMenuKey = (e: KeyboardEvent) => {
    const list = items();
    const i = list.indexOf(document.activeElement as HTMLElement);
    if (e.key === "Escape") {
      e.preventDefault();
      close(true);
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      list[(i + 1) % list.length]?.focus();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      list[(i - 1 + list.length) % list.length]?.focus();
    } else if (e.key === "Home") {
      e.preventDefault();
      list[0]?.focus();
    } else if (e.key === "End") {
      e.preventDefault();
      list[list.length - 1]?.focus();
    } else if (e.key === "Tab") {
      setOpen(false);
    }
  };

  const signOut = async () => {
    setBusy(true);
    setOpen(false);
    try {
      await auth.signOut();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="account-menu" ref={rootRef}>
      <button
        ref={buttonRef}
        type="button"
        className="btn ghost account-menu-button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={onButtonKey}
        disabled={busy}
        data-testid="account-menu"
        title={user.email ?? label}
      >
        <span className="account-avatar" aria-hidden>
          {initials(label)}
        </span>
        <span className="account-name">{label}</span>
        <Icon name="chevron-down" size={14} />
      </button>
      {open ? (
        <ul className="account-menu-list" role="menu" id={menuId} aria-label="Account" ref={listRef} onKeyDown={onMenuKey}>
          <li role="none" className="account-menu-head">
            <strong>{user.display_name || "Signed in"}</strong>
            {user.email}
          </li>
          <li role="none">
            <Link role="menuitem" className="account-menu-item" to="/account" onClick={() => setOpen(false)} data-testid="account-settings">
              <Icon name="settings" /> Account settings
            </Link>
          </li>
          <li role="none">
            <button role="menuitem" type="button" className="account-menu-item" onClick={() => void signOut()} data-testid="sign-out">
              <SignOutIcon /> Sign out
            </button>
          </li>
        </ul>
      ) : null}
    </div>
  );
}
