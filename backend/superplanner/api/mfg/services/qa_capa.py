"""M7 service `qa_capa` (M7-DESIGN; S0: example-backed until implemented)."""

from __future__ import annotations

from . import m7_examples

__getattr__ = m7_examples.module_getattr(__name__)
