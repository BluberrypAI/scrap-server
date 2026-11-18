"""Fill current statutory waste forms with known values only.

Unknown cells stay blank for the user. Birth date is never filled. The signature or seal
image goes over "(서명 또는 인)" in both HWPX and PDF, only when the filer confirms they sign it
themselves; it is never stored.
Classification values come from the confirmed engine handoff unless the filer enters their own
(code, physical state); those are used as the filer's declaration and flagged in warnings.
Field map: docs/specs/legal-forms.md.
"""

import base64
import binascii
import datetime
import json
import re
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

from app.domains.legal_forms.hwpx import CellEdit, fill_hwpx
from app.domains.legal_forms.schemas import (
    FormCompanyIn,
    FormKind,
    FormSubmitIn,
    FormWasteIn,
)

RESOURCES = Path(__file__).parent / "resources"
TEMPLATES: dict[str, str] = {
    "form5": "form5-2026.11.12.hwpx",
    "form6": "form6-2021.7.6.hwpx",
    "form12": "form12-2020.5.27.hwpx",
}
TITLES = {
    "form6": ("제6호 사업장폐기물배출자 신고서", "작성본-제6호-배출자신고서.hwpx"),
    "form12": ("제12호 폐기물 처리계획서", "작성본-제12호-처리계획서.hwpx"),
    "form5": ("제5호 수탁처리능력 확인서 (위탁자 칸)", "작성본-제5호-수탁확인서.hwpx"),
}

# 제5호 3쪽 "폐기물처리 방법별 분류" (2203 does not exist)
METHOD_CODES = frozenset(
    str(c)
    for c in [
        *range(1001, 1012),
        *range(1101, 1118),
        1201,
        1202,
        1203,
        1300,
        1500,
        *range(2001, 2012),
        *range(2101, 2120),
        2201,
        2202,
        2204,
        2205,
        2206,
        2300,
    ]
)
_CLASS = {"0": "재활용", "1": "중간처분", "2": "매립", "3": "해역배출", "5": "수출"}
# Facts guessed by the engine are not written into a legal form.
_UNTRUSTED_SOURCES = {"DERIVED"}
# 서식 대상 분류. 제6호는 GENERAL, 제12호는 DESIGNATED, 제5호는 둘 다
_FORM_CATEGORIES = {"GENERAL", "DESIGNATED"}


class FormInputError(Exception):
    """Input does not satisfy the form rules (shown to the user as is)."""


# Field-level problems: collected (cell left blank) while previewing, raised when making a file.
_PROBLEMS: ContextVar[list[str] | None] = ContextVar("legal_form_problems", default=None)


def _field_problem(message: str) -> str:
    found = _PROBLEMS.get()
    if found is None:
        raise FormInputError(message)
    found.append(message)
    return ""


@dataclass
class Edit:
    cell: int
    expect: str
    op: str
    show: str
    pattern: str | None = None
    before: str = ""
    after: str = ""
    slot: str = ""
    # "at": draw at the measured spot (blank run), no line redraw. Only for op "sub".
    place: str | None = None


@dataclass
class Company:
    name: str | None = None
    business_registration_number: str | None = None
    representative_name: str | None = None
    address: str | None = None
    industrial_complex_name: str | None = None
    phone: str | None = None
    industry: str | None = None
    raw_material: str | None = None
    main_product: str | None = None
    process_flow: str | None = None


@dataclass
class Verdict:
    code: str
    name: str
    category: str
    state: str | None
    warnings: list[str] = field(default_factory=list)


def company_from(profile: Any, override: FormCompanyIn) -> Company:
    """Profile values first, then the user's overrides for this document."""
    base = Company(
        name=getattr(profile, "company_name", None),
        address=getattr(profile, "site_address", None),
        industry=getattr(profile, "industry", None),
        main_product=", ".join(getattr(profile, "main_products", None) or []) or None,
    )
    for key, value in override.model_dump(exclude_none=True).items():
        if value != "":
            setattr(base, key, value)
    return base


# 엔진 결론: 지정폐기물은 확실하지만 세부 분류번호는 확인이 필요한 경우(분류번호 없음)
CODE_NEEDED = "DESIGNATED_CODE_NEEDED"


def is_code_needed(handoff: dict[str, Any]) -> bool:
    return (
        handoff.get("result_type") == "NO_CODE"
        and handoff.get("outcome") == CODE_NEEDED
        and handoff.get("category") == "DESIGNATED"
    )


def verdict_from(handoff: dict[str, Any], waste: FormWasteIn | None = None) -> Verdict:
    code_needed = is_code_needed(handoff)
    if not code_needed:
        if handoff.get("result_type") != "WASTE_CODE" or not handoff.get("waste_code"):
            raise FormInputError("분류번호가 정해진 판정만 서식을 채울 수 있습니다")
        # web의 서식 버튼 조건과 같다.
        # API를 직접 불러도 시험 필요·해석 필요 판정으로는 만들지 않는다.
        if (handoff.get("route_guidance") or {}).get("action") != "RECOMMEND_ROUTE":
            raise FormInputError("처리 경로를 안내하는 판정만 서식을 채울 수 있습니다")
    if handoff.get("category") not in _FORM_CATEGORIES:
        raise FormInputError("사업장일반폐기물·지정폐기물로 판정된 건만 서식을 채울 수 있습니다")
    waste = waste or FormWasteIn()
    warnings: list[str] = []
    if code_needed:
        # 지정폐기물인 것은 확실하므로 번호 칸만 비운 초안을 만든다(번호를 알면 직접 입력).
        code = waste.waste_code or ""
        warnings.append(
            "지정폐기물이지만 세부 분류번호가 정해지지 않았습니다. "
            + ("직접 입력한 분류번호를 썼습니다. " if code else "분류번호 칸을 비웠습니다. ")
            + "번호를 관할 기관이나 이전 신고서·인계서로 확인하기 전까지는 제출 전 초안입니다."
        )
        return Verdict(
            code=code,
            name="",
            category="DESIGNATED",
            state=_state_of(handoff, waste, warnings),
            warnings=warnings,
        )
    engine_code = handoff["waste_code"]
    verified = handoff.get("review") == "VERIFIED"
    code = engine_code if verified else ""
    if waste.waste_code:
        code = waste.waste_code
        if code != engine_code:
            warnings.append(
                f"직접 입력한 분류번호({code})가 문진 판정({engine_code})과 다릅니다. "
                "제출 전에 업체·관할 기관에 확인해 주세요."
            )
        elif not verified:
            warnings.append(
                "직접 확인해 입력한 분류번호를 썼습니다. 문진 판정은 검토 전 규칙 결과입니다."
            )
    elif not verified:
        warnings.append(
            f"검토 전 규칙에 따른 판정({engine_code})이라 분류번호 칸을 비웠습니다. "
            "업체·관할 기관에 확인한 뒤 분류번호 칸에 입력해 주세요."
        )
    state = _state_of(handoff, waste, warnings)
    # The narrow "종류" cell takes the name without the trailing parenthetical note.
    name = re.sub(r"\s*\(.*\)\s*$", "", handoff.get("waste_name") or "")
    return Verdict(
        code=code,
        name=name,
        category=handoff.get("category") or "",
        state=state,
        warnings=warnings,
    )


def _state_of(handoff: dict[str, Any], waste: FormWasteIn, warnings: list[str]) -> str | None:
    state_fact = (handoff.get("facts") or {}).get("physical_state") or {}
    state = state_fact.get("value")
    if waste.physical_state:
        return waste.physical_state
    if state is not None and state_fact.get("source_type") in _UNTRUSTED_SOURCES:
        warnings.append("배출 시 상태가 추정값이라 성질·상태 칸을 비웠습니다. 직접 골라 주세요.")
        return None
    return state if isinstance(state, str) else None


def _num(v: float | int | None) -> str:
    if v is None:
        return ""
    return f"{v:.6f}".rstrip("0").rstrip(".")


def _tons_month(w: FormWasteIn) -> str:
    if w.tons_per_month is not None:
        return _num(w.tons_per_month)
    return _num(w.kg_per_month / 1000 if w.kg_per_month is not None else None)


def _kg_month(w: FormWasteIn) -> str:
    if w.kg_per_month is not None:
        return _num(w.kg_per_month)
    return _num(w.tons_per_month * 1000 if w.tons_per_month is not None else None)


def _state_num(state: str | None, container: bool = False) -> str:
    # 제6·5호: 고체 "1", 액체 "2". Semisolid has no box on the form.
    return "기타" if container else {"solid": "1", "liquid": "2"}.get(state or "", "")


def _state_word(state: str | None, container: bool = False) -> str:
    # 제12호 writes words; containers of designated waste are "기타".
    return "기타" if container else {"solid": "고상", "liquid": "액상"}.get(state or "", "")


def _method(code: str | None, treatment: str | None) -> str:
    if not code:
        return ""
    if code not in METHOD_CODES:
        return _field_problem(f"처리방법 번호 {code}은(는) 제5호 3쪽 분류표에 없습니다")
    want = "1" if treatment == "자가" else "2"
    if treatment and code[0] != want:
        return _field_problem(f'처리방법 번호 {code}이(가) 처리구분 "{treatment}"와 맞지 않습니다')
    return f"{_CLASS[code[1]]}\n{code}"


def _e(cell: int, expect: str, op: str, show: Any, **sub: str) -> list[Edit]:
    if show is None or show == "":
        return []
    return [Edit(cell, expect, op, str(show), **sub)]


def _check(cell: int, expect: str, literal: str = "[ ]") -> list[Edit]:
    return _e(cell, expect, "sub", "√", pattern=re.escape(literal), before="[", after="]")


def _address(cell: int, expect: str, c: Company) -> list[Edit]:
    return [
        *_e(cell, expect, "append", c.address),
        *_e(
            cell,
            expect,
            "sub",
            c.industrial_complex_name,
            pattern=r"산업단지명:\s+,",
            before="산업단지명: ",
            after=",",
        ),
        *_e(
            cell, expect, "sub", c.phone, pattern=r"전화번호:\s+\)", before="전화번호: ", after=")"
        ),
    ]


# 받는 기관장: 서식에 인쇄된 대상 중 하나여야 한다
_RECIPIENT_ENDINGS = {
    "form6": ("특별자치시장", "특별자치도지사", "시장", "군수", "구청장"),
    "form12": ("도지사", "시장", "환경청장"),
}
_RECIPIENT_HINT = {
    "form6": "특별자치시장·특별자치도지사·시장·군수·구청장 (예: 화성시장, 세종특별자치시장)",
    "form12": "시·도지사 또는 유역(지방)환경청장 (예: 경기도지사, 한강유역환경청장)",
}
_DATE_RUN = r"^년\s+월\s+일$"
_SIGN_RUN = r"\(서명 또는 인\)"
MAX_SIGNATURE_BYTES = 200_000


def _date(d: datetime.date | None) -> str:
    return f"{d.year}년 {d.month}월 {d.day}일" if d else ""


def _recipient(kind: str, s: FormSubmitIn) -> str:
    r = (s.recipient or "").strip()
    if r and not r.endswith(_RECIPIENT_ENDINGS[kind]):
        return _field_problem(
            f"받는 기관장은 {_RECIPIENT_HINT[kind]} 중 하나로 적어 주세요. "
            "사람 이름은 적지 않고 직위만 적어요"
        )
    return r


def signature_bytes(kind: str, s: FormSubmitIn) -> bytes | None:
    """서명 이미지(PNG). 신고인 본인 확인이 없으면 쓰지 않는다."""
    if not s.signature_png:
        return None
    if kind == "form5":
        raise FormInputError("제5호의 서명란은 처리 업체(수탁자)가 서명합니다")
    if not s.signer_confirmed:
        raise FormInputError(
            "서명·날인은 신고인 본인(또는 위임받은 사람)이 직접 해야 합니다. "
            "'서명·날인' 칸 아래 확인란을 체크해 주세요"
        )
    head, _, data = s.signature_png.partition(",")
    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        raise FormInputError("서명 이미지를 읽을 수 없습니다. 다시 서명해 주세요") from None
    if head != "data:image/png;base64" or not raw.startswith(b"\x89PNG"):
        raise FormInputError("서명 이미지는 PNG여야 합니다")
    if len(raw) > MAX_SIGNATURE_BYTES:
        raise FormInputError("서명 이미지가 너무 큽니다")
    return raw


def _head(c: Company, first: int) -> list[Edit]:
    """①~⑨ rows shared by 제6호 (first=16) and 제12호 (first=14)."""
    return [
        *_e(first, "① 상호", "append", c.name),
        *_e(first + 1, "② 사업자등록번호", "append", c.business_registration_number),
        *_e(first + 2, "③ 성명", "append", c.representative_name),
        *_address(first + 4, "⑤ 주소", c),
        *_e(first + 7, "⑥ 업종", "append", c.industry),
        *_e(first + 8, "⑦ 주 원료명", "append", c.raw_material),
        *_e(first + 9, "⑧ 주 생산품명", "append", c.main_product),
        *_e(first + 10, "⑨ 제조공정", "append", c.process_flow),
    ]


def _tail(w: FormWasteIn, row: int) -> list[Edit]:
    """운반·처리 columns shared by 제6호 and 제12호 (row = first transport cell)."""
    return [
        *_e(row, "", "set", w.carrier),
        *_e(row + 1, "", "set", _num(w.carried_tons)),
        *_e(row + 2, "", "set", w.treatment),
        *_e(row + 3, "", "set", w.vendor),
        *_e(row + 4, "", "set", _method(w.method, w.treatment)),
        *_e(row + 5, "", "set", _num(w.treated_tons_per_year)),
    ]


def _form6(v: Verdict, c: Company, w: FormWasteIn, s: FormSubmitIn) -> list[Edit]:
    if v.category == "DESIGNATED":
        raise FormInputError("지정폐기물은 제6호가 아니라 처리계획서(제12호) 대상입니다")
    r = 45  # first cell of the first waste row
    return [
        *_check(3, "[ ] 신고서"),
        *_head(c, 16),
        *_e(r, "", "set", w.group),
        *_e(r + 1, "", "set", v.name),
        *_e(r + 2, "□□-□□-□□", "set", v.code),
        *_e(r + 3, "", "set", _state_num(v.state)),
        *_e(r + 4, "", "set", _tons_month(w)),
        *_e(r + 5, "", "set", _num(w.tons_per_year)),
        *_tail(w, r + 6),
        *_check(77, "[ ] 제18조제2항", "[ ] "),
        *_check(81, "[ ] 신고"),
        *_e(84, "년", "sub", _date(s.date), pattern=_DATE_RUN),
        *_e(
            85,
            "신고인",
            "sub",
            s.signer_name or c.representative_name,
            pattern=r"신고인\s+$",
            before="신고인   ",
        ),
        *_e(86, "(서명", "sign", "(서명)" if s.signature_png else None, pattern=_SIGN_RUN),
        *_e(
            87,
            "특별자치시장",
            "sub",
            _recipient("form6", s),
            pattern=r"특별자치시장, 특별자치도지사, 시장ㆍ군수ㆍ구청장",
        ),
    ]


def _form12(v: Verdict, c: Company, w: FormWasteIn, s: FormSubmitIn) -> list[Edit]:
    if v.category != "DESIGNATED":
        raise FormInputError("처리계획서(제12호)는 지정폐기물만 해당합니다")
    r = 42
    if w.carrier == "자가":
        carry = _check(79, "[ ]자가")
    elif w.carrier:
        carry = [
            *_check(80, "[ ]위탁"),
            *_e(
                80,
                "[ ]위탁",
                "sub",
                w.carrier,
                pattern=r"업소명:\s+\)",
                before="업소명: ",
                after=")",
            ),
        ]
    else:
        carry = []
    return [
        *_head(c, 14),
        *_e(r, "", "set", w.designated_kind),
        *_e(r + 1, "□□-□□-□□", "set", v.code),
        *_e(r + 2, "", "set", _kg_month(w)),
        *_e(r + 3, "", "set", _num(w.tons_per_year)),
        *_e(r + 4, "", "set", w.frequency),
        *_e(r + 5, "", "set", _state_word(v.state, w.container)),
        *_tail(w, r + 6),
        *carry,
        *_e(83, "「폐기물관리법」", "sub", _date(s.date), pattern=_DATE_RUN),
        *_e(
            83,
            "「폐기물관리법」",
            "sub",
            s.signer_name or c.representative_name,
            pattern=r"^\s{20,}$",
            # Keep spaces on both sides so the name sits between "제출인" and "(서명 또는 인)".
            before=" " * 6,
            after=" " * 20,
            place="at",
        ),
        *_e(
            83,
            "「폐기물관리법」",
            "sign",
            "(서명)" if s.signature_png else None,
            pattern=_SIGN_RUN,
        ),
        *_e(
            83,
            "「폐기물관리법」",
            "sub",
            _recipient("form12", s),
            pattern=r"시ㆍ도지사, 유역\(지방\)환경청장",
        ),
    ]


def _form5(v: Verdict, c: Company, w: FormWasteIn, s: FormSubmitIn) -> list[Edit]:
    # 위탁자(배출 기업) cells ①~⑥ only; the vendor fills the rest.
    code = v.code or "    -    -    "
    return [
        *_check(2, "[ ] 수탁처리능력"),
        *_e(6, "① 상호", "append", c.name),
        *_e(7, "② 사업자등록번호", "append", c.business_registration_number),
        *_e(8, "③ 성명", "append", c.representative_name),
        *_e(10, "⑤ 주소", "sub", c.address, pattern=r"\(사업장\)\s+$", before="(사업장)  "),
        *_e(
            10, "⑤ 주소", "sub", c.phone, pattern=r"전화번호:\s+\)", before="전화번호: ", after=")"
        ),
        *_e(18, "(", "set", v.name and f"{v.name}\n({code})"),
        *_e(19, "", "set", _state_num(v.state, w.container and v.category == "DESIGNATED")),
        *_e(20, "", "set", _num(w.tons_per_year)),
    ]


_SPECS = {"form6": _form6, "form12": _form12, "form5": _form5}


def form_edits(
    kind: FormKind,
    verdict: Verdict,
    company: Company,
    waste: FormWasteIn,
    submit: FormSubmitIn | None = None,
    problems: list[str] | None = None,
) -> list[Edit]:
    """problems: when given, field problems are added there and those cells stay blank
    (preview); otherwise the first problem raises FormInputError (file)."""
    submit = submit or FormSubmitIn()
    token = _PROBLEMS.set(problems)
    try:
        edits = _SPECS[kind](verdict, company, waste, submit)
    finally:
        _PROBLEMS.reset(token)
    seen: dict[int, int] = {}
    for e in edits:
        seen[e.cell] = seen.get(e.cell, -1) + 1
        e.slot = f"{e.cell}.{seen[e.cell]}"
    return edits


@cache
def read_template(kind: str) -> bytes:
    return (RESOURCES / TEMPLATES[kind]).read_bytes()


_HU_PER_CM = 2835  # HWPUNIT: 1/7200 inch


@cache
def read_layout(kind: str) -> dict:
    """Measured positions (pt, page top-left) shared by the PDF and the signature picture."""
    return json.loads((RESOURCES / f"{kind}-layout.json").read_text(encoding="utf-8"))


def png_size(png: bytes) -> tuple[int, int]:
    return int.from_bytes(png[16:20], "big"), int.from_bytes(png[20:24], "big")


def mark_box_cm(png: bytes, mark_type: str, compact: bool = False) -> tuple[float, float]:
    """Printed size of the signature/seal: signature about 1 cm tall, seal about 1.6 cm.

    compact (HWPX): a little smaller, since the picture hangs below the line top there.
    """
    w, h = png_size(png)
    ratio = w / h if h else 1
    height, max_width = (1.6, 2.0) if mark_type == "seal" else (1.0, 4.0)
    if compact:
        height, max_width = height * 0.75, max_width * 0.75
    width = min(height * ratio, max_width)
    return width, width / ratio if ratio else height


def form_hwpx(
    kind: FormKind,
    edits: list[Edit],
    template: bytes | None = None,
    mark: Any = None,
    signature: bytes | None = None,
    mark_type: str = "signature",
) -> bytes:
    """mark(edit) -> str | None: probe text instead of the value (layout measuring only)."""

    def value(e: Edit) -> str:
        show = (mark(e) if mark else None) or e.show
        return e.before + show + e.after if e.op in ("sub", "sign") else show

    cells = [
        CellEdit(
            e.cell,
            e.expect,
            "sub" if e.op == "sign" else e.op,  # type: ignore[arg-type]
            value(e),
            e.pattern,
        )
        for e in edits
        if e.op != "sign" or (mark and mark(e))
    ]
    if signature and not mark:
        # Hung from the "(서명 또는 인)" line, right-aligned like the text itself.
        w_cm, h_cm = mark_box_cm(signature, mark_type, compact=True)
        cells += [
            CellEdit(
                e.cell,
                e.expect,
                "image",
                "",
                e.pattern,
                image=signature,
                image_size=(round(w_cm * _HU_PER_CM), round(h_cm * _HU_PER_CM)),
            )
            for e in edits
            if e.op == "sign"
        ]
    return fill_hwpx(template or read_template(kind), cells)
