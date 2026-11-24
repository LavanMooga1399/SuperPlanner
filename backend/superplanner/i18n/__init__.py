"""Server-side message catalog (M7-DESIGN 0.11): notification and digest texts in English and French (Canada).
`t(key, locale, **values)`; unknown locales and keys fall back to English (then to the key)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

LOCALES = ("en", "fr-CA")
_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=4)
def catalog(locale: str) -> dict[str, str]:
    name = {"en": "messages_en.json", "fr-CA": "messages_fr_CA.json"}.get(locale, "messages_en.json")
    return json.loads((_DIR / name).read_text(encoding="utf-8"))


def t(key: str, locale: str | None = None, **values: Any) -> str:
    text = catalog(locale or "en").get(key) or catalog("en").get(key) or key
    try:
        return text.format(**values)
    except (KeyError, IndexError):
        return text


def plant_locale(plant: Any) -> str:
    loc = ((getattr(plant, "attributes", None) or {}).get("locale") if plant is not None else None) or "en"
    return loc if loc in LOCALES else "en"


__all__ = ["LOCALES", "catalog", "plant_locale", "t"]
