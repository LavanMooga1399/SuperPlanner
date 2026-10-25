"""Plant row (M1-DESIGN 3.3, 6.1; review R6; PLAN-M1 A1-4): reads never insert; `lock_plant` creates lazily, bumps
`data_version`, and two concurrent first writes of one owner both commit on PostgreSQL."""

from __future__ import annotations

import threading
import time

import pytest
from sqlalchemy import func, select

from superplanner.api.db.ownership import owner_scope
from superplanner.api.mfg import repo
from superplanner.api.mfg.db_models import MFG_MODELS, MfgPlantRow


def _total_rows(db) -> int:
    with db.read() as s:
        return sum(s.execute(select(func.count()).select_from(m)).scalar_one() for m in MFG_MODELS)


def test_reads_insert_nothing(mfg_db):
    with owner_scope("usr_a"), mfg_db.read() as s:
        p = repo.plant_or_default(s)
        assert (p.id, p.row_version, p.data_version, p.name, p.utc_offset) == (None, 0, 0, "Plant", "+00:00")
        ds = repo.load_dataset(s)
        assert ds.items == {} and ds.plant.id is None
        assert repo.bom_edge_list(s) == []
    assert _total_rows(mfg_db) == 0


def test_lock_plant_creates_once_and_bumps_data_version(mfg_db):
    with owner_scope("usr_a"):
        for expected in (1, 2):
            with mfg_db.write() as s:
                row = repo.lock_plant(s)
                assert row.data_version == expected and row.owner_id == "usr_a"
        with mfg_db.read() as s:
            p = repo.plant_or_default(s)
            assert p.data_version == 2 and p.row_version == 1 and p.id.startswith("plt_")
            assert p.created_at.tzinfo is not None
    with owner_scope("usr_b"), mfg_db.write() as s:
        assert repo.lock_plant(s).data_version == 1                 # per owner
    with owner_scope("usr_a"), mfg_db.read() as s:
        assert s.execute(select(func.count()).select_from(MfgPlantRow)).scalar_one() == 1


def test_get_row_is_owned(mfg_db):
    from superplanner.api.errors import ApiError

    with owner_scope("usr_a"), mfg_db.write() as s:
        pid = repo.lock_plant(s).id
    with owner_scope("usr_a"), mfg_db.read() as s:
        assert repo.get_row(s, MfgPlantRow, pid, what="Plant").id == pid
    with owner_scope("usr_b"), mfg_db.read() as s:
        with pytest.raises(ApiError) as exc:
            repo.get_row(s, MfgPlantRow, pid, what="Plant", lock=True)
        assert exc.value.status == 404 and exc.value.code == "NOT_FOUND"


@pytest.mark.postgres_only
def test_concurrent_first_writes_both_commit(mfg_db):
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []
    seen: list[int] = []

    def writer(hold: float) -> None:
        try:
            with owner_scope("usr_a"):
                barrier.wait()
                with mfg_db.write() as s:
                    row = repo.lock_plant(s)
                    seen.append(row.data_version)
                    time.sleep(hold)            # the first one keeps its insert uncommitted for a moment
        except BaseException as exc:  # pragma: no cover - reported below
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(0.5,)), threading.Thread(target=writer, args=(0.0,))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert not errors, errors
    assert sorted(seen) == [1, 2]
    with owner_scope("usr_a"), mfg_db.read() as s:
        rows = s.execute(select(MfgPlantRow)).scalars().all()
        assert len(rows) == 1 and rows[0].data_version == 2
