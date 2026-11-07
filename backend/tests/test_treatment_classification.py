import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from app.domains.treatment import classification
from app.domains.treatment.repository import replace_snapshots


@pytest.mark.parametrize(
    ("profile", "seed"),
    [
        ("pp-injection-scrap", {"material": "pp", "resin_stream": "ordinary_resin"}),
        ("pp-shredded", {"material": "pp"}),
        ("pe-film", {"material": "pe"}),
        ("pet-bottle", {"material": "pet", "resin_stream": "discarded_packaging"}),
        ("aluminium-beverage-can", {"material": "metal_can"}),
    ],
)
async def test_profile_starts_team_classifier_with_known_facts_only(
    client, monkeypatch, profile, seed
):
    async def upstream(method, path, *, json):
        assert (method, path) == ("POST", "/sessions")
        assert json == {"answers": {"physical_state": "solid", **seed}, "waste_id": "sample"}
        return httpx.Response(200, json={"session_id": uuid4().hex, "phase": "question"})

    monkeypatch.setattr("app.domains.treatment.router.classifier_request", upstream)
    profiles = await client.get("/api/classification/profiles")
    assert profiles.status_code == 200
    assert profile in {row["profile"] for row in profiles.json()}
    response = await client.post(
        "/api/classification/sessions", json={"profile": profile, "waste_id": "sample"}
    )
    assert response.status_code == 200
    assert response.json()["phase"] == "question"
    conflict = await client.post(
        "/api/classification/sessions", json={"profile": profile, "answers": {"material": "paper"}}
    )
    assert conflict.status_code == 422


@pytest.mark.parametrize(
    ("code", "material", "form"),
    [
        ("51-03-01", "PP", "film"),
        ("51-03-07", "PP", "scrap"),
        ("51-03-07", "PET", "bale"),
        ("51-29-03", "aluminium", "scrap"),
    ],
)
async def test_out_of_scope_initial_combinations_do_not_return_candidates(
    client, db, code, material, form
):
    await replace_snapshots(db)
    response = await client.post(
        "/api/treatment/next-step",
        json={"waste_code": code, "material": material, "input_form": form},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "unsupported"
    assert response.json()["options"] == []


async def test_session_uses_recorded_r_codes_and_holds_unclear_lots(client, db, monkeypatch):
    await replace_snapshots(db)
    session = uuid4()
    record = {
        "record_version": "1",
        "complete": True,
        "open_items": [],
        "material": {"id": "pp"},
        "items": {
            "code": {"status": "PROVISIONAL", "code": "51-03-01"},
            "designated": {"value": "NOT_DESIGNATED"},
            "recycling": {
                "prohibited": False,
                "allowed": [{"r_code": "R-10", "pre_analysis_required": True}],
            },
        },
        "hazards": {
            key: {"state": "VALUE", "value": value}
            for key, value in classification.CLEAN_FACTS.items()
        },
    }

    def upstream(request):
        assert request.url.path == f"/api/classification/sessions/{session.hex}/record"
        return httpx.Response(200, content=json.dumps(record))

    client_factory = httpx.AsyncClient
    monkeypatch.setattr(
        classification.httpx,
        "AsyncClient",
        lambda **_: client_factory(transport=httpx.MockTransport(upstream)),
    )
    monkeypatch.setattr(
        classification,
        "get_settings",
        lambda: SimpleNamespace(classification_base_url="http://engine"),
    )
    params = {
        "waste_code": "51-03-01",
        "material": "PP",
        "input_form": "scrap",
        "classification_session_id": str(session),
        "recycling_types": {"free": ["R-10"]},
    }
    result = (await client.post("/api/treatment/next-step", json=params)).json()
    assert result["status"] == "candidates"
    assert result["options"][0]["recycling_types"] == {
        "free": [],
        "analysis": ["R-10"],
        "unmarked": [],
    }
    assert result["dispatch_approved"] is False

    record["hazards"]["oil_presence"] = {"state": "UNKNOWN"}

    result = (await client.post("/api/treatment/next-step", json=params)).json()
    assert result["status"] == "review_required"
    assert result["options"] == []
