# Load test (M8-DESIGN 14.2)

The BD-like data set and the k6 scenarios L1-L3. k6 is an external binary (https://k6.io); nothing here is a
Python or npm dependency.

## 1. Seed

    cd backend
    DATABASE_URL=postgresql+psycopg://... .venv/bin/python -m superplanner.manage load-seed --profile bd [--email E]
    # or: .venv/bin/python scripts/load/seed.py --profile bd

`bd`: 40 flow lines, 6 EtO chambers + aeration room, 3,000 SKUs (1,800 finished / 1,200 bought), BOMs, routings,
24 months of history, 6,000 open order lines, item planning, packaging, line rates. It **replaces** the plant's
manufacturing data of the user (default: the local user). Then run the chain once (forecast, SS, MRP pass 1, rate
run, ster plan, MRP pass 2): `POST /api/v1/mfg/planning/nightly/run-now` (or the slow test below).

Performance cases P1-P5, P8 are measured by `pytest -m slow tests/api_mfg_m8/test_m8_perf.py -s` (prints the
timings; the `small` profile of the same test runs in the normal suite).

## 2. Run the API and workers

Production-like: `JOB_BACKEND=queue`, `WORKER_KINDS` covering the M8 kinds, `RATE_WORKERS=4`, a read replica if
available (`DATABASE_READ_URL`).

## 3. k6

    export BASE_URL=http://127.0.0.1:8000 EMAIL=owner@example.com PASSWORD=...   # or TOKEN=<api token>
    k6 run backend/scripts/load/k6/l1_read_mix.js            # L1: 300 VUs, 30 min, p95 < 800 ms, errors < 0.1 %
    k6 run backend/scripts/load/k6/l2_floor_events.js        # L2: 2,000 floor events/h with L1, p95 < 300 ms
    VUS=50 k6 run backend/scripts/load/k6/l3_nightly_under_load.js   # L3: nightly chain under 50 users

Options by environment: `VUS`, `DURATION`, `EVENTS_PER_HOUR`, `WORKSPACE` (member accounts), `TOKEN`.

## 4. Report (M8 Gate)

Record machine (CPU, RAM, disk, PostgreSQL version and settings), data size (the seed's output), the P1-P9
timings and the k6 summaries (p50 / p95 / p99, error rate) for L1-L3. The BD-scale sign-off on production-class
hardware is M10.
