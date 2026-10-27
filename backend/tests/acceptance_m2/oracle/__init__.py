"""Independent MRP oracle for M2 Gate 2 #2 (WP-D). Must never import `superplanner.mfg.mrp`."""

from .core import INTERPRETATIONS, Oracle, OracleError, run_oracle  # noqa: F401
from .model import OPlant, OResult  # noqa: F401
