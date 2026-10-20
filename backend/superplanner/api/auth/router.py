"""Auth endpoints under `/api/v1/auth` (PHASE2B 4.5). Q1 stub: the router exists and is wired (without
`require_user`); Q3 adds `/session`, `/sign-up`, `/sign-in`, `/sign-out`, `/change-password`."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/auth", tags=["auth"])
