"""Default assumptions (FINANCE.md section 5). Illustrative, user-editable, never fetched from the network.

The raw data lives here as plain tuples so `model.py` can use it for field defaults without an import cycle;
`default_assumptions()` builds the pydantic objects.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from .model import Assumptions

DISCLAIMER = (
    "SuperPlanner Finance is an educational planning tool. It is not investment, tax or legal advice and "
    "does not recommend specific financial products. Results are estimates based on the assumptions you "
    "entered; actual returns, inflation and income can differ, and you could end up with less than your "
    "goals need. Consider consulting a qualified, registered investment adviser before making investment "
    "decisions."
)
DISCLAIMER_VERSION = "fin-disclaimer-1"
FINANCE_ENGINE_VERSION = "fin-0.1.0"

SOURCE_NOTE = "Illustrative long-run assumptions, not forecasts. Edit them to match your own view."

# (id, name, category, expected_return_pct, volatility_pct, expense_ratio_pct, liquidity_days, lock_in_months)
ASSET_CLASSES: tuple[tuple[str, str, str, float, float, float, int, int], ...] = (
    ("cash", "Cash / savings account", "cash", 3.0, 0.5, 0.0, 0, 0),
    ("fixed_deposit", "Fixed deposit", "debt", 6.75, 1.0, 0.0, 2, 0),
    ("short_debt", "Short-term debt fund", "debt", 7.0, 2.0, 0.35, 2, 0),
    ("govt_long", "Government long lock-in savings (PPF-like)", "debt", 7.1, 0.5, 0.0, 7, 180),
    ("equity_index", "Diversified equity index fund", "equity", 11.5, 18.0, 0.2, 3, 0),
    ("gold", "Gold", "gold", 8.0, 15.0, 0.4, 3, 0),
)

CORRELATIONS: tuple[tuple[str, str, float], ...] = (
    ("cash", "fixed_deposit", 0.5),
    ("fixed_deposit", "short_debt", 0.5),
    ("short_debt", "govt_long", 0.3),
    ("equity_index", "short_debt", 0.1),
    ("gold", "short_debt", 0.1),
    ("equity_index", "gold", 0.0),
)

RISKY_CAP_BY_TOLERANCE_PCT: tuple[float, ...] = (20.0, 40.0, 60.0, 75.0, 90.0)

GLIDE_PATH: tuple[tuple[int, float], ...] = ((120, 1.0), (84, 0.85), (60, 0.70), (36, 0.50), (24, 0.35),
                                             (12, 0.20), (0, 0.0))

INFLATION_PCT = 6.0
INFLATION_VOLATILITY_PCT = 1.5
CASH_CLASS_ID = "cash"
EF_CLASS_ID = "fixed_deposit"
EF_MONTHS = 6.0

# Default minimum success probability by priority (section 4.8).
DEFAULT_MIN_PROBABILITY = {"must": 0.85, "should": 0.70, "nice": 0.50}

RESERVED_IDS = frozenset({"emergency_fund", "cash_buffer", "unallocated"})
WHATIF_PREFIX = "whatif_"

RISKY_CATEGORIES = frozenset({"equity", "gold", "other"})
EQUITY_CATEGORIES = frozenset({"equity"})

# Preflight / size limits (sections 6, 8.7).
MAX_HORIZON_MONTHS = 600
MAX_LP_VARIABLES = 60_000
MAX_BINARIES = 2000

LIMITS = {"goals": 12, "incomes": 20, "expenses": 100, "debts": 20, "holdings": 50, "one_offs": 200,
          "asset_classes": 10, "horizon_months": MAX_HORIZON_MONTHS}


def default_asset_classes_data() -> list[dict]:
    return [dict(id=i, name=n, category=c, expected_return_pct=r, volatility_pct=v, expense_ratio_pct=e,
                 liquidity_days=liq, lock_in_months=lock)
            for (i, n, c, r, v, e, liq, lock) in ASSET_CLASSES]


def default_correlations_data() -> list[dict]:
    return [dict(a=a, b=b, rho=rho) for (a, b, rho) in CORRELATIONS]


def default_glide_data() -> list[dict]:
    return [dict(min_months_to_goal=m, multiplier=x) for (m, x) in GLIDE_PATH]


def default_assumptions() -> "Assumptions":
    from .model import Assumptions

    return Assumptions()
