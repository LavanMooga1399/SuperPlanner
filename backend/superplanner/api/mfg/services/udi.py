"""UDI device records, GS1 parsing and GUDID / Health Canada export files (M10-DESIGN 7.1, 7.5)."""

from __future__ import annotations

from typing import Any

from . import m10_examples


__getattr__ = m10_examples.module_getattr(__name__)
