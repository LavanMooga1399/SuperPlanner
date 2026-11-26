"""Demo review: in demo mode the assistant answers "why is DO-MDV-1003 late and what can I do" on the meddev_m8
sample with citations and at least one draft action."""

from __future__ import annotations

import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "assistant"))

from apimfgm2_helpers import Api, make_app  # noqa: E402


def test_demo_assistant_drafts_for_meddev_late_order(db_url):
    from superplanner.assistant.fake import DemoClient

    client = DemoClient()
    with TestClient(make_app(db_url, assistant_ai_enabled=True,
                             assistant_ai_client_factory=lambda: client)) as c:
        api = Api(c)
        api.load("meddev_m8")
        conv = api.post("/assistant/conversations", {})["id"]
        acc = api.post(f"/assistant/conversations/{conv}/turns",
                       {"text": "Why is DO-MDV-1003 late and what can I do?"}, status=202)
        t0 = time.monotonic()
        while (turn := api.get(f"/assistant/turns/{acc['turn_id']}"))["status"] in ("queued", "running"):
            assert time.monotonic() - t0 < 120
            time.sleep(0.05)
        assert turn["status"] == "completed", (turn, client.errors)
        assert turn["citations"], turn["answer"]
        assert turn["drafts"], [s for s in turn["steps"]]
