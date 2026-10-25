"""A1-2 (M1-DESIGN 6.2, review R7): constraint/index names <= 63 characters, an index led by owner_id on every
mfg table, and an index led by every FK column."""

from __future__ import annotations

import sqlalchemy as sa

from superplanner.api.db import load_all_models
from superplanner.api.mfg.db_models import MFG_MODELS, MFG_TABLES


def _tables():
    md = load_all_models()
    return [md.tables[t] for t in MFG_TABLES]


def _leading(t: sa.Table) -> list[tuple[str, ...]]:
    """Column tuples of every index-backed structure: indexes, unique constraints, primary key."""
    out = [tuple(c.name for c in ix.columns) for ix in t.indexes]
    out += [tuple(c.name for c in uc.columns) for uc in t.constraints if isinstance(uc, sa.UniqueConstraint)]
    out.append(tuple(c.name for c in t.primary_key.columns))
    return out


def test_eighteen_owned_tables():
    assert len(MFG_TABLES) == 18 and all(t.startswith("mfg_") for t in MFG_TABLES)
    assert all("owner_id" in m.__table__.columns for m in MFG_MODELS)


def test_names_fit_postgres_identifier_limit():
    names = []
    for t in _tables():
        names += [ix.name for ix in t.indexes]
        names += [c.name for c in t.constraints if c.name is not None]
    assert names and all(len(n) <= 63 for n in names), [n for n in names if len(n) > 63]
    assert "fk_mfg_shift_assignments_shift_template_id_mfg_shift_templates" in names


def test_every_table_has_an_owner_led_index():
    for t in _tables():
        assert any(cols and cols[0] == "owner_id" for cols in _leading(t)), t.name


def test_every_fk_column_leads_an_index():
    for t in _tables():
        leads = {cols[0] for cols in _leading(t) if cols}
        for fk in t.foreign_keys:
            assert fk.parent.name in leads, (t.name, fk.parent.name)


def test_no_server_defaults_and_named_fks():
    for t in _tables():
        assert all(c.server_default is None for c in t.columns), t.name
        assert all(fk.name and fk.name.startswith(f"fk_{t.name}_") for fk in t.foreign_key_constraints)
