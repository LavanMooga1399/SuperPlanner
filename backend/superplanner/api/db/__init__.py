"""Persistence layer (ARCHITECTURE 13, PHASE2B 3)."""

from .models import (AuditEventRow, Base, JobRow, JobWorkerRow, ProblemRow, ProblemVersionRow, ScheduleRow,
                     SolverRunEventRow, SolverRunRow, new_id, utcnow)
from .ownership import LOCAL_USER_ID, OwnedMixin
from .session import Database


def load_all_models():
    """Import every module that registers tables on `Base` and return the complete metadata (56 tables: the 16
    scheduling/finance/auth tables + the 18 M1 and 22 M2 and 10 M3 `mfg_*` tables)."""
    from ..auth import models as _auth_models  # noqa: F401
    from ..finance import db_models as _finance_db_models  # noqa: F401
    from ..mfg import db_models as _mfg_db_models  # noqa: F401
    from ..mfg import db_models_m2 as _mfg_db_models_m2  # noqa: F401
    from ..mfg import db_models_m3 as _mfg_db_models_m3  # noqa: F401

    return Base.metadata


__all__ = ["AuditEventRow", "Base", "Database", "JobRow", "JobWorkerRow", "LOCAL_USER_ID", "OwnedMixin",
           "ProblemRow", "ProblemVersionRow", "ScheduleRow", "SolverRunEventRow", "SolverRunRow", "load_all_models",
           "new_id", "utcnow"]
