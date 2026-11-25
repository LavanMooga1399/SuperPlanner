"""M8 service `kanban` (M8-DESIGN 11). Functions not defined yet answer from the S0 examples (`m8_examples`)."""

from __future__ import annotations

from . import m8_examples

__getattr__ = m8_examples.module_getattr(__name__)
