"""Exercise the owner and unauthenticated routes with synthetic data."""

import hashlib
import logging
import re
import uuid
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.domains.companies.models import Company
from app.domains.transport.models import WorkflowInquiryReplyLink, WorkflowLot
from app.main import app
from tests.test_inquiry_replies import PDF
from tests.test_pp_company_workflow import setup_flow as _setup_flow
from tests.test_vendor_inquiry import reviewed, selection

setup_flow = _setup_flow
PUBLIC_PATH = "/api/v1/public/inquiry-replies"
MISSING = f"{PUBLIC_PATH}/{'x' * 43}"


@pytest.fixture
async def public_client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.fixture
async def inquiry(setup_flow):
    req, create, actors, _ = setup_flow
    lot = await reviewed(req, await create())
    body = selection(lot, unregistered=True)
    base = f"/lots/{lot['id']}/inquiries/{body['capability_key']}"
    return req, lot, body, base, actors


async def issue(req, base):
    response = await req("A", base + "/reply-link")
    assert response.status_code == 201, response.text
    return response.json()


def assert_protected(response):
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-robots-tag"] == "noindex"


async def post_reply(client, url, fields=None, file=None):
    parts = {k: (None, v) for k, v in (fields or {}).items()}
    if file:
        parts["file"] = file
    return await client.post(url, files=parts)


async def test_only_current_company_can_manage_link(inquiry, db, public_client):
    req, lot, _, base, actors = inquiry
    path = base + "/reply-link"
    assert (await req("A", path, method="GET")).json() == {"status": "none", "expires_at": None}
    for method in ("GET", "POST", "DELETE"):
        assert (await public_client.request(method, "/api/v1/workflow" + path)).status_code == 401
        assert (await req("D", path, method=method)).status_code == 404
    await issue(req, base)
    stored_lot = await db.get(WorkflowLot, uuid.UUID(lot["id"]))
    stored_lot.current_company_id = uuid.UUID(actors["B"][1])
    await db.commit()
    for method in ("GET", "POST", "DELETE"):
        assert (await req("A", path, method=method)).status_code == 403
    assert (await req("B", path, method="GET")).json() == {"status": "none", "expires_at": None}


async def test_link_rotation_replaces_hash_and_resets_count(inquiry, db, public_client):
    req, _, _, base, _ = inquiry
    first = await issue(req, base)
    old_url = f"{PUBLIC_PATH}/{first['token']}"
    assert (
        await post_reply(public_client, old_url, {"availability": "conditional"})
    ).status_code == 201
    second = await issue(req, base)
    assert second["token"] != first["token"]
    assert set(second) == {"status", "token", "path", "expires_at"}
    assert second["status"] == "active"
    assert second["path"] == f"/#/reply/{second['token']}"
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", second["token"])
    expires = datetime.fromisoformat(second["expires_at"])
    assert timedelta(days=13, hours=23) < expires - datetime.now(UTC) < timedelta(days=14)
    status = (await req("A", base + "/reply-link", method="GET")).json()
    assert status == {"status": "active", "expires_at": second["expires_at"]}
    rows = (await db.scalars(select(WorkflowInquiryReplyLink))).all()
    assert len(rows) == 1
    assert rows[0].token_hash == hashlib.sha256(second["token"].encode()).hexdigest()
    assert (await public_client.get(old_url)).status_code == 404
    assert (
        await post_reply(public_client, old_url, {"availability": "available"})
    ).status_code == 404
    assert (await public_client.get(f"{PUBLIC_PATH}/{second['token']}")).json()["reply_count"] == 0
    assert len((await req("A", base + "/replies", method="GET")).json()) == 1


@pytest.mark.parametrize("reason", ["expired", "revoked", "completed", "cancelled", "excluded"])
async def test_unusable_links_share_one_public_404(inquiry, public_client, db, reason):
    req, lot, body, base, _ = inquiry
    issued = await issue(req, base)
    url = f"{PUBLIC_PATH}/{issued['token']}"
    if reason == "revoked":
        assert (await req("A", base + "/reply-link", method="DELETE")).status_code == 204
        assert (await req("A", base + "/reply-link", method="DELETE")).status_code == 204
    elif reason == "expired":
        row = await db.scalar(select(WorkflowInquiryReplyLink))
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db.commit()
    else:
        stored = await db.get(WorkflowLot, uuid.UUID(lot["id"]))
        if reason == "excluded":
            review = deepcopy(stored.review)
            for option in review["next_step"]["options"]:
                option["facilities"] = [
                    f for f in option["facilities"] if f["capability_key"] != body["capability_key"]
                ]
            stored.review = review
        else:
            stored.status = reason
        await db.commit()
    status = (await req("A", base + "/reply-link", method="GET")).json()
    assert status["status"] == ("expired" if reason == "expired" else "revoked")
    responses = (
        await public_client.get(MISSING),
        await public_client.get(url),
        await post_reply(public_client, url, {"availability": "available"}),
        await post_reply(public_client, url),
    )
    for response in responses:
        assert response.status_code == 404, response.text
        assert response.content == responses[0].content
        assert_protected(response)


async def test_public_inquiry_reuses_packet_and_omits_private_fields(inquiry, public_client, db):
    req, lot, body, base, actors = inquiry
    company = await db.get(Company, uuid.UUID(actors["A"][1]))
    company.site_address = "경기도 시흥시 산단로 123-4 (정왕동)"
    stored = await db.get(WorkflowLot, uuid.UUID(lot["id"]))
    review = deepcopy(stored.review)
    facilities = [(o, f) for o in review["next_step"]["options"] for f in o["facilities"]]
    option, facility = next(
        (o, f) for o, f in facilities if f["capability_key"] == body["capability_key"]
    )
    facility.update(road_distance_status="available", road_distance_km=24.5)
    stored.review = review
    await db.commit()

    issued = await issue(req, base)
    response = await public_client.get(f"{PUBLIC_PATH}/{issued['token']}")
    assert response.status_code == 200, response.text
    assert_protected(response)
    packet = (await req("A", f"/lots/{lot['id']}/inquiry-packet", body)).json()
    payload = response.json()
    assert set(payload) == {
        "sender_company_name",
        "facility_label",
        "subject",
        "inquiry_text",
        "summary",
        "expires_at",
        "reply_count",
        "max_replies",
    }
    assert payload["sender_company_name"] == "A"
    assert payload["facility_label"] == facility["label"]
    assert payload["subject"] == packet["subject"]
    assert payload["expires_at"] == issued["expires_at"]
    assert payload["reply_count"] == 0 and payload["max_replies"] == 10
    expected_summary = {
        # The state label already starts with the material, so it is not repeated.
        "item": option["input_state"]["label"],
        "weight_kg": 1000,
        "condition": "합성 테스트 PP, 실제 물량 아님",
        "waste_code": lot["data"]["initial"]["waste_code"],
        "origin_region": "경기도 시흥시",
        "road_distance_km": 24.5,
        "process": f"{option['input_state']['label']} → {option['output_state']['label']}",
        "questions": [
            "이 물량의 반입 가능 여부",
            "반입 조건 (선별·세척 상태, 포장, 최소 수량 등)",
            "처리 단가와 가능한 일정",
        ],
    }
    assert payload["summary"] == expected_summary
    assert "123-4" in payload["inquiry_text"]
    link = await db.scalar(select(WorkflowInquiryReplyLink))
    assert link.inquiry["summary"] == expected_summary
    assert "mail_body" not in link.inquiry
    without_timestamp = r"^생성 시각\(UTC\): .+$"
    assert re.sub(without_timestamp, "", payload["inquiry_text"], flags=re.M) == re.sub(
        without_timestamp, "", packet["text"], flags=re.M
    )
    for forbidden in (
        "/photos/",
        lot["id"],
        lot["current_company_id"],
        body["capability_key"],
        "@example.com",
        issued["token"],
    ):
        assert forbidden not in response.text
    other_labels = {f["label"] for _, f in facilities} - {facility["label"]}
    assert other_labels
    assert all(label not in payload["inquiry_text"] for label in other_labels)
    assert not public_client.cookies


async def test_public_summary_keeps_issue_time_values(inquiry, public_client, db):
    req, lot, _, base, actors = inquiry
    issued = await issue(req, base)
    url = f"{PUBLIC_PATH}/{issued['token']}"
    original = (await public_client.get(url)).json()["summary"]
    assert original["road_distance_km"] is None
    company = await db.get(Company, uuid.UUID(actors["A"][1]))
    company.site_address = "서울특별시 마포구 변경로 123"
    stored = await db.get(WorkflowLot, uuid.UUID(lot["id"]))
    stored.data = {**stored.data, "current": {**stored.data["current"], "mass_kg": 300}}
    await db.commit()
    response = await public_client.get(url)
    assert response.status_code == 200, response.text
    assert response.json()["summary"] == original


async def test_public_legacy_snapshot_reads_with_null_summary(inquiry, public_client, db):
    req, _, _, base, _ = inquiry
    issued = await issue(req, base)
    link = await db.scalar(select(WorkflowInquiryReplyLink))
    link.inquiry = {key: value for key, value in link.inquiry.items() if key != "summary"}
    await db.commit()

    response = await public_client.get(f"{PUBLIC_PATH}/{issued['token']}")
    assert response.status_code == 200, response.text
    assert response.json()["summary"] is None
    assert response.json()["inquiry_text"] == link.inquiry["inquiry_text"]


async def test_access_log_hides_only_public_reply_token(inquiry, public_client, caplog):
    req, _, _, base, _ = inquiry
    issued = await issue(req, base)
    url = f"{PUBLIC_PATH}/{issued['token']}"
    assert (await public_client.get(url)).status_code == 200
    logger = logging.getLogger("uvicorn.access")
    with caplog.at_level(logging.INFO, logger=logger.name):
        for path in (url, "/health"):
            logger.info('%s - "%s %s HTTP/%s" %d', "127.0.0.1", "GET", path, "1.1", 200)
    assert issued["token"] not in caplog.text
    assert f"{PUBLIC_PATH}/{{token}}" in caplog.text
    assert "/health" in caplog.text


@pytest.mark.parametrize(
    ("fields", "file"),
    [
        ({}, None),
        ({"availability": "maybe"}, None),
        ({"availability": "available", "text": "x" * 2001}, None),
        ({"availability": "available", "contact_name": "x" * 101}, None),
        ({"availability": "available", "contact_info": "x" * 201}, None),
        ({"availability": "available"}, ("견적.pdf", b"MZ fake", "application/pdf")),
        ({"availability": "available"}, ("견적.pdf", b"", "application/pdf")),
        ({"availability": "available"}, ("견적.pdf", PDF.ljust(10 * 1024 * 1024 + 1), "x/y")),
    ],
)
async def test_public_reply_validates_fields_and_attachment(inquiry, public_client, fields, file):
    req, _, _, base, _ = inquiry
    issued = await issue(req, base)
    url = f"{PUBLIC_PATH}/{issued['token']}"
    response = await post_reply(public_client, url, fields, file)
    assert response.status_code == 422, response.text
    assert set(response.json()) == {"code", "message", "details"}
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert_protected(response)
    assert (await public_client.get(url)).json()["reply_count"] == 0


async def test_public_reply_appears_in_sender_list_with_attachment(inquiry, public_client):
    req, _, _, base, _ = inquiry
    issued = await issue(req, base)
    url = f"{PUBLIC_PATH}/{issued['token']}"
    response = await post_reply(
        public_client,
        url,
        {
            "availability": "conditional",
            "text": " 주중 반입 ",
            "contact_name": " 시험 담당 ",
            "contact_info": "vendor@example.com",
        },
        ("../견적.pdf", PDF, "text/html"),
    )
    assert response.status_code == 201, response.text
    assert_protected(response)
    created = response.json()
    assert set(created) == {"id", "created_at"}
    replies = (await req("A", base + "/replies", method="GET")).json()
    assert replies == [
        {
            "id": created["id"],
            "created_at": replies[0]["created_at"],
            "text": "주중 반입",
            "received_on": None,
            "file": {"name": "견적.pdf", "size": len(PDF), "mime": "application/pdf"},
            "source": "vendor_link",
            "availability": "conditional",
            "contact_name": "시험 담당",
            "contact_info": "vendor@example.com",
        }
    ]
    reply_path = f"/inquiry-replies/{created['id']}"
    assert (await req("D", reply_path + "/file", method="GET")).status_code == 404
    assert (await req("A", reply_path + "/file", method="GET")).content == PDF
    payload = (await public_client.get(url)).json()
    assert payload["reply_count"] == 1
    assert "vendor@example.com" not in str(payload)
    assert (await req("A", reply_path, method="DELETE")).status_code == 204


async def test_each_link_accepts_ten_total_even_after_reply_deletion(inquiry, public_client):
    req, _, _, base, _ = inquiry
    issued = await issue(req, base)
    url = f"{PUBLIC_PATH}/{issued['token']}"
    for _ in range(10):
        response = await post_reply(public_client, url, {"availability": "unavailable"})
        assert response.status_code == 201, response.text
    reply_id = response.json()["id"]
    assert (await req("A", f"/inquiry-replies/{reply_id}", method="DELETE")).status_code == 204
    assert (await public_client.get(url)).json()["reply_count"] == 10
    response = await post_reply(public_client, url, {"availability": "available"})
    assert response.status_code == 429
    assert response.json()["code"] == "RATE_LIMITED"
    assert_protected(response)
    assert len((await req("A", base + "/replies", method="GET")).json()) == 9


async def test_memory_rate_limit_per_token_and_ip(inquiry, public_client, monkeypatch):
    req, _, _, base, _ = inquiry
    issued = await issue(req, base)
    url = f"{PUBLIC_PATH}/{issued['token']}"
    now = 600
    monkeypatch.setattr("app.domains.transport.public_inquiry_replies.monotonic", lambda: now)
    monkeypatch.setattr(app.state, "inquiry_reply_rate_limit_enabled", True)
    for _ in range(10):
        assert (await public_client.get(url)).status_code == 200
    # Same IP, different token.
    assert (await public_client.get(MISSING)).status_code == 429
    other_transport = ASGITransport(app=app, client=("192.0.2.15", 1234))
    async with AsyncClient(transport=other_transport, base_url="http://test") as other_ip:
        response = await post_reply(other_ip, url, {"availability": "available"})
        # Same token, different IP.
        assert response.status_code == 429 and response.json()["code"] == "RATE_LIMITED"
        assert_protected(response)
        now += 60
        assert (await other_ip.get(url)).status_code == 200
