"""Synthetic data. Replies are registered by hand; nothing is sent or received."""

import pytest

from app.domains.transport.inquiry_replies import clean_filename
from tests.test_pp_company_workflow import setup_flow as _setup_flow
from tests.test_vendor_inquiry import reviewed, selection

setup_flow = _setup_flow
PDF = b"%PDF-1.4 synthetic"


async def reply_setup(req, create):
    lot = await reviewed(req, await create())
    key = selection(lot)["capability_key"]
    return lot, key, f"/lots/{lot['id']}/inquiries/{key}/replies"


async def test_packet_has_short_single_line_subject(setup_flow):
    req, create, _, _ = setup_flow
    lot = await reviewed(req, await create())
    res = await req("A", f"/lots/{lot['id']}/inquiry-packet", selection(lot))
    subject = res.json()["subject"]
    assert subject.startswith("[반입조건 문의] A - ") and "1000kg" in subject
    assert len(subject) <= 120 and "\n" not in subject


async def test_reply_register_list_download_delete(setup_flow):
    req, create, _, _ = setup_flow
    _, _, path = await reply_setup(req, create)
    assert (await req("A", path, method="GET")).json() == []
    res = await req(
        "A",
        path,
        data={"text": "견적 회신", "received_on": "2026-11-01"},
        files={"file": ("../회신 견적.pdf", PDF, "text/html")},
    )
    assert res.status_code == 200, res.text
    assert res.headers["cache-control"] == "private, no-store"
    await req("A", path, data={"text": "두번째"})
    items = (await req("A", path, method="GET")).json()
    assert [i["text"] for i in items] == ["두번째", "견적 회신"]
    item = items[1]
    assert item["received_on"] == "2026-11-01" and items[0]["file"] is None
    assert item["file"] == {"name": "회신 견적.pdf", "mime": "application/pdf", "size": len(PDF)}
    assert set(item) == {
        "id",
        "text",
        "received_on",
        "file",
        "created_at",
        "source",
        "availability",
        "contact_name",
        "contact_info",
    }
    assert item["source"] == "sender"
    assert item["availability"] is item["contact_name"] is item["contact_info"] is None
    file_path = f"/inquiry-replies/{item['id']}/file"
    got = await req("A", file_path, method="GET")
    assert got.content == PDF and got.headers["content-type"] == "application/pdf"
    assert got.headers["content-disposition"].startswith("attachment; filename*=UTF-8''")
    assert got.headers["x-content-type-options"] == "nosniff"
    assert got.headers["cache-control"] == "private, no-store"
    assert (await req("D", file_path, method="GET")).status_code == 404
    assert (await req("D", f"/inquiry-replies/{item['id']}", method="DELETE")).status_code == 404
    assert (await req("A", f"/inquiry-replies/{item['id']}", method="DELETE")).status_code == 204
    assert len((await req("A", path, method="GET")).json()) == 1
    assert (await req("A", file_path, method="GET")).status_code == 404


async def test_reply_denies_other_company_and_unknown_candidate(setup_flow):
    req, create, _, _ = setup_flow
    lot, _, path = await reply_setup(req, create)
    assert (await req("D", path, data={"text": "x"})).status_code == 404
    assert (await req("D", path, method="GET")).status_code == 404
    bad = f"/lots/{lot['id']}/inquiries/not-a-candidate/replies"
    assert (await req("A", bad, data={"text": "x"})).status_code == 404
    odd = f"/lots/{lot['id']}/inquiries/a b/replies"
    assert (await req("A", odd, data={"text": "x"})).status_code == 422


@pytest.mark.parametrize(
    ("fields", "status"),
    [
        ({}, 422),
        ({"text": "  "}, 422),
        ({"text": "x", "received_on": "2999-01-01"}, 422),
        ({"text": "x", "received_on": "11/01"}, 422),
        ({"text": "x" * 5001}, 422),
        ({"file": ("a.pdf", b"MZ\x90 exe", "application/pdf")}, 422),
        ({"file": ("a.exe", PDF, "application/pdf")}, 422),
        ({"file": ("a.pdf", b"", "application/pdf")}, 422),
        ({"file": ("a.docx", PDF, "application/octet-stream")}, 422),
        ({"file": ("a.pdf", PDF + b"0" * (10 * 1024 * 1024), "application/pdf")}, 413),
    ],
)
async def test_reply_rejects_bad_input(setup_flow, fields, status):
    req, create, _, _ = setup_flow
    _, _, path = await reply_setup(req, create)
    files = {"file": fields.pop("file")} if "file" in fields else None
    res = await req("A", path, data=fields, files=files)
    assert res.status_code == status, res.text
    assert (await req("A", path, method="GET")).json() == []


async def test_reply_accepts_each_signature_and_cleans_name(setup_flow):
    req, create, _, _ = setup_flow
    _, _, path = await reply_setup(req, create)
    cases = [
        ("a.png", b"\x89PNG\r\n\x1a\n.."),
        ("a.JPG", b"\xff\xd8\xff\xe0.."),
        ("a.webp", b"RIFF\x00\x00\x00\x00WEBPVP8 "),
        ("a.xlsx", b"PK\x03\x04.."),
        ("a.hwpx", b"PK\x03\x04.."),
        ("a.hwp", b"\xd0\xcf\x11\xe0.."),
        ("C:\\x\\y\\evil.docx", b"PK\x03\x04.."),
        ("가" * 300 + ".pdf", PDF),
    ]
    for name, body in cases:
        res = await req("A", path, data={}, files={"file": (name, body, "x/y")})
        assert res.status_code == 200, (name, res.text)
    names = [i["file"]["name"] for i in res.json()]
    assert "evil.docx" in names and all(len(n) <= 200 for n in names)
    assert next(n for n in names if n.startswith("가")).endswith(".pdf")


def test_filename_cleaning_drops_controls_and_paths():
    assert clean_filename("../a/b\\ev\x01il.pdf") == "evil.pdf"


async def test_reply_limit_50_per_inquiry(setup_flow):
    req, create, _, _ = setup_flow
    _, _, path = await reply_setup(req, create)
    for i in range(50):
        assert (await req("A", path, data={"text": str(i)})).status_code == 200
    assert (await req("A", path, data={"text": "51"})).status_code == 409
