"""Keep per-lot requests within one wave of three independent model calls."""

import json
from functools import partial
from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr

from app.domains.treatment.intake import review_intakes


@pytest.mark.parametrize("with_lot,sizes", [(True, [3, 3, 1]), (False, [5, 2])])
async def test_lot_batch_budget_preserves_successes_and_every_failed_candidate(
    monkeypatch, with_lot, sizes
):
    batches = []
    packets = [{"capability_key": f"site-{i}", "next_check": "확인 필요"} for i in range(7)]

    def respond(request):
        body = json.loads(request.content)
        batch = body["candidates"]
        batches.append([p["capability_key"] for p in batch])
        assert ("lot_context" in body) == with_lot
        if len(batches) == 2:
            raise httpx.ReadTimeout("synthetic timeout", request=request)
        return httpx.Response(
            200,
            json={
                "results": {
                    p["capability_key"]: {"status": "needs_evidence", "next_check": p["next_check"]}
                    for p in batch
                }
            },
        )

    monkeypatch.setattr(
        "app.domains.treatment.intake.httpx.AsyncClient",
        partial(httpx.AsyncClient, transport=httpx.MockTransport(respond)),
    )
    result = await review_intakes(
        packets,
        SimpleNamespace(
            ai_base_url="http://route.test",
            scrap_intake_service_token=SecretStr("synthetic-service-token"),
        ),
        lot_context={"photos": [], "condition": "synthetic"} if with_lot else None,
    )
    assert [len(b) for b in batches] == sizes
    assert set(result.results) == {p["capability_key"] for p in packets}
    failed = set(batches[1])
    for key, item in result.results.items():
        assert item.status == ("model_unavailable" if key in failed else "needs_evidence")
        assert item.dispatch_approved is False
