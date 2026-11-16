"""A completed HTTP request must not turn a missing model review into a green audit."""

import argparse
import importlib.util
import json
from functools import partial
from pathlib import Path

import httpx
import pytest


@pytest.mark.parametrize(
    "status,expected_exit",
    [("reviewed", 0), ("needs_evidence", 0), ("model_unavailable", 1)],
)
async def test_live_audit_distinguishes_evidence_hold_from_call_failure(
    monkeypatch, tmp_path, status, expected_exit
):
    script = Path(__file__).parents[2] / "scripts" / "audit_live_ai.py"
    spec = importlib.util.spec_from_file_location("live_ai_audit_test", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "capabilities": [{"key": "test-site--test-process", "reachable": True}],
                "queries": [
                    {
                        "capabilities": ["test-site--test-process"],
                        "request": {"material": "pe", "input_form": "film"},
                    }
                ],
            }
        ),
        encoding="utf8",
    )

    def respond(request):
        if request.url.path == "/api/v1/auth/dev-login":
            return httpx.Response(200, json={})
        assert request.url.path == "/api/treatment/intake-reviews"
        return httpx.Response(
            200,
            json={
                "results": {
                    "test-site--test-process": {"status": status, "dispatch_approved": False}
                }
            },
        )

    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        partial(httpx.AsyncClient, transport=httpx.MockTransport(respond)),
    )
    output = tmp_path / "result.json"
    result = await module.run(
        argparse.Namespace(
            catalog=str(catalog),
            output=str(output),
            base="http://localhost:5178",
            concurrency=1,
            delay=0,
        )
    )
    assert result == expected_exit
    assert (
        json.loads(output.read_text("utf8"))["requests"][0]["results"]["test-site--test-process"][
            "status"
        ]
        == status
    )
