"""법정 서식 작성본 (spec: docs/specs/legal-forms.md). 회사·업체 값은 모두 가상."""

import base64
import datetime
import io
import zipfile
from copy import deepcopy

import httpx
import pytest

from app.domains.diagnosis.client import get_engine_client
from app.domains.legal_forms import service
from app.domains.legal_forms.hwpx import CellEdit, TemplateMismatchError, fill_hwpx, hwpx_cells
from app.domains.legal_forms.schemas import FormCompanyIn, FormSubmitIn, FormWasteIn
from app.main import app
from tests.test_diagnosis import FakeEngine

COMPANY = FormCompanyIn(
    name="(주)가천정밀",
    business_registration_number="123-45-67890",
    representative_name="홍길동",
    address="경기도 화성시 팔탄면 산업로 128",
    industrial_complex_name="화성바이오밸리",
    phone="031-000-0000",
    industry="플라스틱 사출 성형제품 제조업",
    raw_material="폴리프로필렌 수지 120톤/년",
    main_product="자동차 내장 사출품 110톤/년",
    process_flow="원료 입고 - 건조 - 사출 성형 - 검사 - 포장 - 출하",
)
GENERAL = {
    "contract": "diagnosis-handoff-v1",
    "case_id": "C1",
    "result_type": "WASTE_CODE",
    "waste_code": "51-03-01",
    "waste_name": "폐합성수지류(폐염화비닐수지류는 제외한다)",
    "category": "GENERAL",
    "route_guidance": {"action": "RECOMMEND_ROUTE"},
    "review": "VERIFIED",
    "facts": {
        "material": {"value": "pp", "source_type": "UTTERANCE"},
        "physical_state": {"value": "solid", "source_type": "UTTERANCE"},
    },
}
DESIGNATED = {
    **GENERAL,
    "waste_code": "02-01-01",
    "waste_name": "폐염산",
    "category": "DESIGNATED",
    "facts": {"physical_state": {"value": "liquid", "source_type": "UTTERANCE"}},
}
WASTE6 = FormWasteIn(
    group=1,
    tons_per_month=3,
    tons_per_year=36,
    carrier="○○자원(주)",
    carried_tons=36,
    treatment="위탁",
    vendor="○○자원(주)",
    method="2003",
    treated_tons_per_year=36,
)
WASTE12 = FormWasteIn(
    designated_kind="폐산",
    kg_per_month=800,
    tons_per_year=9.6,
    frequency="1회/월",
    carrier="△△환경(주)",
    carried_tons=9.6,
    treatment="위탁",
    vendor="△△환경(주)",
    method="2116",
    treated_tons_per_year=9.6,
)


def make(kind, handoff, waste, company=COMPANY):
    verdict = service.verdict_from(handoff, waste)
    edits = service.form_edits(kind, verdict, service.company_from(None, company), waste)
    return hwpx_cells(service.form_hwpx(kind, edits))


def with_(base, **over):
    h = deepcopy(base)
    h.update(over)
    return h


# ---- 서식 채우기 ----


def test_form6_keeps_original_cells_and_fills_values():
    c = make("form6", GENERAL, WASTE6)
    assert "별지 제6호서식" in c[0] and "2021. 7. 6." in c[0]
    assert "① 상호(명칭)" in c[16] and c[16].endswith("(주)가천정밀")
    assert "산업단지명: 화성바이오밸리, 전화번호: 031-000-0000)" in c[20]
    assert c[45:57] == [
        "1",
        "폐합성수지류",
        "51-03-01",
        "1",
        "3",
        "36",
        "○○자원(주)",
        "36",
        "위탁",
        "○○자원(주)",
        "재활용2003",
        "36",
    ]
    assert c[3].startswith("[√] 신고서")
    assert c[19] == "④ 생년월일", "생년월일은 채우지 않는다"


def test_form12_uses_words_and_kg_per_month():
    c = make("form12", DESIGNATED, WASTE12)
    assert c[42:48] == ["폐산", "02-01-01", "800", "9.6", "1회/월", "액상"]
    assert "[√]위탁(업소명: △△환경(주))" in c[80]


def test_form12_self_carrier_checks_self_box():
    c = make("form12", DESIGNATED, WASTE12.model_copy(update={"carrier": "자가"}))
    assert c[79].startswith("[√]자가")
    assert "[√]" not in c[80]


def test_form5_fills_only_consignor_cells():
    c = make("form5", GENERAL, WASTE6)
    assert c[6].endswith("(주)가천정밀")
    assert c[18:21] == ["폐합성수지류(51-03-01)", "1", "36"]
    assert c[33] == "", "수탁자 칸은 업체가 쓴다"


def test_result_is_valid_hwpx_zip():
    verdict = service.verdict_from(GENERAL)
    edits = service.form_edits("form6", verdict, service.company_from(None, COMPANY), WASTE6)
    z = zipfile.ZipFile(io.BytesIO(service.form_hwpx("form6", edits)))
    first = z.infolist()[0]
    assert first.filename == "mimetype" and first.compress_type == zipfile.ZIP_STORED
    assert z.testzip() is None


def test_unverified_verdict_leaves_code_blank_with_warning():
    h = with_(GENERAL, review="UNVERIFIED")
    assert make("form6", h, WASTE6)[47] == "□□-□□-□□"
    assert any("분류번호 칸을 비웠습니다" in w for w in service.verdict_from(h).warnings)


def test_derived_state_is_not_written():
    h = with_(GENERAL)
    h["facts"]["physical_state"]["source_type"] = "DERIVED"
    assert make("form6", h, WASTE6)[48] == ""
    assert any("추정값" in w for w in service.verdict_from(h).warnings)


def test_semisolid_has_no_box():
    h = with_(GENERAL)
    h["facts"]["physical_state"]["value"] = "semisolid"
    assert make("form6", h, WASTE6)[48] == ""


@pytest.mark.parametrize(
    ("method", "treatment", "message"),
    [("2203", "위탁", "분류표에 없습니다"), ("1101", "위탁", "맞지 않습니다")],
)
def test_method_code_is_checked(method, treatment, message):
    w = WASTE6.model_copy(update={"method": method, "treatment": treatment})
    with pytest.raises(service.FormInputError, match=message):
        make("form6", GENERAL, w)


def test_category_must_match_form():
    with pytest.raises(service.FormInputError, match="제12호"):
        make("form6", DESIGNATED, WASTE6)
    with pytest.raises(service.FormInputError, match="지정폐기물만"):
        make("form12", GENERAL, WASTE12)


def test_profile_values_are_defaults_and_overrides_win():
    profile = type(
        "P",
        (),
        {
            "company_name": "가상사출(주)",
            "site_address": "시흥",
            "industry": "사출",
            "main_products": ["범퍼"],
        },
    )()
    c = service.company_from(profile, FormCompanyIn(industry="플라스틱 사출 성형제품 제조업"))
    assert (c.name, c.address, c.main_product) == ("가상사출(주)", "시흥", "범퍼")
    assert c.industry == "플라스틱 사출 성형제품 제조업"


def test_changed_template_stops_instead_of_filling_wrong_cell():
    with pytest.raises(TemplateMismatchError, match="서식 칸 16"):
        fill_hwpx(service.read_template("form6"), [CellEdit(16, "② 사업자등록번호", "append", "x")])


# ---- API ----

BASE = "/api/v1/diagnosis/cases/C1/legal-forms"
BODY = {
    "company": {"business_registration_number": "123-45-67890"},
    "waste": WASTE6.model_dump(exclude_none=True),
}


@pytest.fixture
def fake_engine():
    fake = FakeEngine()
    app.dependency_overrides[get_engine_client] = fake.client
    yield fake
    app.dependency_overrides.pop(get_engine_client, None)


def confirmed(handoff, status="CODE_CONFIRMED"):
    return httpx.Response(
        200, json={"case": {"id": "C1", "status": status}, "handoff": deepcopy(handoff)}
    )


async def test_requires_login(client, fake_engine):
    res = await client.post(f"{BASE}/form6/preview", json=BODY)
    assert res.status_code == 401


async def test_unconfirmed_case_is_rejected(company_client, fake_engine):
    fake_engine.reply = confirmed(GENERAL, status="DIAGNOSING")
    res = await company_client.post(f"{BASE}/form6", json=BODY)
    assert res.status_code == 409
    assert res.json()["code"] == "CASE_NOT_CONFIRMED"


async def test_other_company_case_is_not_found(company_client, fake_engine):
    detail = {"code": "CASE_NOT_FOUND", "message": "없음", "details": {}}
    fake_engine.reply = httpx.Response(404, json={"detail": detail})
    res = await company_client.post(f"{BASE}/form6", json=BODY)
    assert res.status_code == 404
    # The engine is asked with this company's id, so other companies' cases never match.
    assert fake_engine.last.headers["X-Company-Id"]


async def test_preview_lists_slots_and_uses_profile(company_client, fake_engine):
    fake_engine.reply = confirmed(with_(GENERAL, review="UNVERIFIED"))
    res = await company_client.post(f"{BASE}/form6/preview", json=BODY)
    assert res.status_code == 200
    assert res.headers["cache-control"] == "no-store"
    body = res.json()
    shown = {e["slot"]: e["show"] for e in body["edits"]}
    assert shown["16.0"] == "가상사출(주)", "상호는 기업 프로필 기본값"
    assert shown["17.0"] == "123-45-67890"
    assert "47.0" not in shown, "검토 전 판정은 분류번호를 비운다"
    phone_or_check = next(e for e in body["edits"] if e["slot"] == "3.0")
    assert phone_or_check["op"] == "sub" and phone_or_check["pattern"]
    assert body["problem"] is None
    assert any("분류번호" in w for w in body["warnings"])


async def test_preview_reports_problem_without_failing(company_client, fake_engine):
    fake_engine.reply = confirmed(DESIGNATED)
    res = await company_client.post(f"{BASE}/form6/preview", json=BODY)
    assert res.status_code == 200
    assert "제12호" in res.json()["problem"]


async def test_download_returns_hwpx_and_ignores_browser_code(company_client, fake_engine):
    fake_engine.reply = confirmed(GENERAL)
    # 최상위·company에 섞어 보낸 분류번호는 무시한다 (사용자 입력은 waste.waste_code만)
    company = {**BODY["company"], "waste_code": "99-99-99"}
    body = {**BODY, "waste_code": "99-99-99", "company": company}
    res = await company_client.post(f"{BASE}/form6", json=body)
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/hwp+zip"
    assert res.headers["cache-control"] == "no-store"
    assert "filename*=UTF-8''" in res.headers["content-disposition"]
    cells = hwpx_cells(res.content)
    assert cells[47] == "51-03-01"
    assert cells[16].endswith("가상사출(주)")


async def test_download_rejects_bad_method(company_client, fake_engine):
    fake_engine.reply = confirmed(GENERAL)
    body = {**BODY, "waste": {**BODY["waste"], "method": "2203"}}
    res = await company_client.post(f"{BASE}/form6", json=body)
    assert res.status_code == 422
    assert "분류표" in res.json()["message"]


async def test_unknown_kind_is_rejected(company_client, fake_engine):
    res = await company_client.post(f"{BASE}/form13", json=BODY)
    assert res.status_code == 422


# ---- PDF ----


def _pdf(kind, handoff, waste):
    from app.domains.legal_forms import pdf

    verdict = service.verdict_from(handoff)
    edits = service.form_edits(kind, verdict, service.company_from(None, COMPANY), waste)
    return pdf.form_pdf(kind, edits)


@pytest.mark.parametrize(
    ("kind", "handoff", "waste"),
    [
        ("form6", GENERAL, WASTE6),
        ("form12", DESIGNATED, WASTE12),
        ("form12", DESIGNATED, WASTE12.model_copy(update={"carrier": "자가"})),
        ("form5", GENERAL, WASTE6),
    ],
)
def test_pdf_keeps_blank_form_pages_and_draws_values(kind, handoff, waste):
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(_pdf(kind, handoff, waste)))
    blank = PdfReader(service.RESOURCES / f"{kind}-blank.pdf")
    assert len(reader.pages) == len(blank.pages), "작성 방법 쪽도 그대로 둔다"
    text = reader.pages[0].extract_text()
    assert "123-45-67890" in text.replace(" ", "")


def test_pdf_layout_covers_every_edit_slot():
    """서식 규칙을 바꾸면 미리보기·PDF 위치 자료도 다시 만들어야 한다."""
    import json

    cases = [
        ("form6", GENERAL, WASTE6),
        ("form12", DESIGNATED, WASTE12),
        ("form12", DESIGNATED, WASTE12.model_copy(update={"carrier": "자가"})),
        ("form5", GENERAL, WASTE6),
    ]
    for kind, handoff, waste in cases:
        layout = json.loads((service.RESOURCES / f"{kind}-layout.json").read_text("utf-8"))
        verdict = service.verdict_from(handoff)
        submit = FormSubmitIn() if kind == "form5" else SIGNED
        company = service.company_from(None, COMPANY)
        for e in service.form_edits(kind, verdict, company, waste, submit):
            slot = layout["slots"].get(e.slot)
            assert slot and ("group" not in slot or slot["group"] in layout["groups"]), e.slot


async def test_download_pdf(company_client, fake_engine):
    fake_engine.reply = confirmed(GENERAL)
    res = await company_client.post(f"{BASE}/form6?format=pdf", json=BODY)
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"
    assert res.headers["cache-control"] == "no-store"
    assert res.content.startswith(b"%PDF")
    assert "%EC%9E%91%EC%84%B1%EB%B3%B8" in res.headers["content-disposition"]  # 작성본
    assert res.headers["content-disposition"].endswith(".pdf")


async def test_unknown_format_is_rejected(company_client, fake_engine):
    fake_engine.reply = confirmed(GENERAL)
    res = await company_client.post(f"{BASE}/form6?format=docx", json=BODY)
    assert res.status_code == 422


# ---- 제출 칸: 작성일, 받는 기관장, 신고인, 서명 / 사용자가 입력한 분류번호·성질상태 ----


def _png() -> bytes:
    """1x1 PNG (서명 이미지 대역)."""
    import struct
    import zlib

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    idat = zlib.compress(b"\x00\x00\x00\x00\xff")
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


SIG = "data:image/png;base64," + base64.b64encode(_png()).decode()
SIGNED = FormSubmitIn(
    date=datetime.date(2026, 11, 17),
    recipient="화성시장",
    signature_png=SIG,
    signer_confirmed=True,
)


def _edits(kind, handoff, waste, submit):
    verdict = service.verdict_from(handoff, waste)
    return service.form_edits(kind, verdict, service.company_from(None, COMPANY), waste, submit)


def test_form6_submit_cells_and_signature_stays_out_of_hwpx():
    c = hwpx_cells(service.form_hwpx("form6", _edits("form6", GENERAL, WASTE6, SIGNED)))
    assert c[84] == "2026년 11월 17일"
    assert c[85].split() == ["신고인", "홍길동"], "신고인 이름은 대표자 성명"
    assert c[86].strip() == "(서명 또는 인)", "서명 이미지는 PDF에만 넣는다"
    assert c[87].split() == ["화성시장", "귀하"]


def test_form12_submit_cells():
    submit = SIGNED.model_copy(update={"recipient": "한강유역환경청장", "signer_name": "김대리"})
    c = hwpx_cells(service.form_hwpx("form12", _edits("form12", DESIGNATED, WASTE12, submit)))
    assert "2026년 11월 17일" in c[83] and "김대리" in c[83] and "한강유역환경청장" in c[83]
    assert "시ㆍ도지사" not in c[83]


@pytest.mark.parametrize(
    ("kind", "handoff", "waste", "recipient"),
    [("form6", GENERAL, WASTE6, "경기도지사"), ("form12", DESIGNATED, WASTE12, "화성시장님")],
)
def test_recipient_must_be_one_of_printed_heads(kind, handoff, waste, recipient):
    submit = FormSubmitIn(recipient=recipient)
    with pytest.raises(service.FormInputError, match="받는 기관장"):
        _edits(kind, handoff, waste, submit)


def test_signature_needs_signer_confirmation():
    unconfirmed = SIGNED.model_copy(update={"signer_confirmed": False})
    with pytest.raises(service.FormInputError, match="본인"):
        _edits("form6", GENERAL, WASTE6, unconfirmed)


def test_signature_must_be_png_and_not_on_form5():
    bad = SIGNED.model_copy(update={"signature_png": "data:image/png;base64,aGVsbG8="})
    with pytest.raises(service.FormInputError, match="PNG"):
        _edits("form6", GENERAL, WASTE6, bad)
    with pytest.raises(service.FormInputError, match="수탁자"):
        _edits("form5", GENERAL, WASTE6, SIGNED)


def test_pdf_draws_signature_image_only_when_given():
    from pypdf import PdfReader

    from app.domains.legal_forms import pdf

    def images(data):
        res = PdfReader(io.BytesIO(data)).pages[0]["/Resources"]
        xo = res.get("/XObject") or {}
        return [k for k, v in xo.items() if v.get_object().get("/Subtype") == "/Image"]

    edits = _edits("form6", GENERAL, WASTE6, SIGNED)
    signed = pdf.form_pdf("form6", edits, service.signature_bytes("form6", SIGNED))
    unsigned = pdf.form_pdf("form6", _edits("form6", GENERAL, WASTE6, FormSubmitIn()))
    assert len(images(signed)) > len(images(unsigned))
    text = PdfReader(io.BytesIO(signed)).pages[0].extract_text().replace(" ", "")
    assert "2026년11월17일" in text and "화성시장" in text


def test_filer_code_is_used_and_flagged():
    unverified = with_(GENERAL, review="UNVERIFIED")
    same = WASTE6.model_copy(update={"waste_code": "51-03-01"})
    assert make("form6", unverified, same)[47] == "51-03-01"
    other = WASTE6.model_copy(update={"waste_code": "51-03-02"})
    verdict = service.verdict_from(unverified, other)
    assert verdict.code == "51-03-02"
    assert any("문진 판정(51-03-01)과 다릅니다" in w for w in verdict.warnings)


def test_filer_state_overrides_guess():
    h = with_(GENERAL)
    h["facts"]["physical_state"]["source_type"] = "DERIVED"
    waste = WASTE6.model_copy(update={"physical_state": "liquid"})
    assert service.verdict_from(h, waste).state == "liquid"
    assert make("form6", h, waste)[48] == "2"


def test_bad_code_format_is_rejected_by_schema():
    with pytest.raises(ValueError):
        FormWasteIn(waste_code="510301")


async def test_preview_lists_sign_slot_and_notes(company_client, fake_engine):
    fake_engine.reply = confirmed(GENERAL)
    body = {**BODY, "submit": {**SIGNED.model_dump(mode="json")}}
    res = await company_client.post(f"{BASE}/form6/preview", json=body)
    data = res.json()
    assert data["problem"] is None
    ops = {e["slot"]: e["op"] for e in data["edits"]}
    assert ops["86.0"] == "sign"
    assert any("PDF에만" in w for w in data["warnings"])


async def test_download_pdf_with_signature(company_client, fake_engine):
    fake_engine.reply = confirmed(GENERAL)
    body = {**BODY, "submit": {**SIGNED.model_dump(mode="json")}}
    res = await company_client.post(f"{BASE}/form6?format=pdf", json=body)
    assert res.status_code == 200 and res.content.startswith(b"%PDF")
    unconfirmed = {**body, "submit": {**body["submit"], "signer_confirmed": False}}
    res = await company_client.post(f"{BASE}/form6?format=pdf", json=unconfirmed)
    assert res.status_code == 422
