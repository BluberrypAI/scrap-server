"""Read explicit form statements already returned by diagnosis; never classify waste."""

import re
from datetime import datetime

from app.domains.treatment.process import normalize_form

# Deliberately narrow: a process word alone (세척/파쇄/사출) is not a current form.
FORM_WORDS = {
    "film-bale": r"(?:폐?비닐|필름)\s*(?:압축\s*)?베일|압축\s*(?:폐?비닐|필름)",
    "shredded": r"파쇄[품물]|분쇄[품물]|shredded\s+(?:plastic|scraps?)|regrind",
    "flake": r"플레이크|\bflakes?\b",
    "pellet": r"펠[릿렛]|\bpellets?\b",
    "bale": r"(?:압축\s*)?베일|\bbales?\b",
    "scrap": r"사출\s*(?:잔재|잔여물|자투리|불량품)|제조\s*잔재|자투리|스크랩|\bscraps?\b",
    "rigid": r"경질\s*(?:제품|부품|플라스틱)|폐\s*(?:파렛트|팔레트|상자)",
    "film": r"필름|폐비닐|\bfilms?\b",
    "bottle": r"(?:PET|페트)\s*병|\bbottles?\b",
    "can": r"알루미늄\s*(?:음료\s*)?캔|음료\s*캔|\bUBC\b",
    "drum": r"(?:폐?철|철제)\s*드럼|200\s*[lL리터]+\s*(?:폐?철|철제)?\s*드럼",
    "net": r"폐어망|폐\s*어망",
    "buoy": r"폐부표|스티로폼\s*부표|EPS\s*부표",
    "ingot": r"인고트|\bingots?\b",
    "foam": r"스티로폼|감용\s*전\s*EPS|EPS\s*폼",
    "wallpaper": r"폐벽지|PVC\s*벽지|실크\s*벽지",
}
UNCERTAIN = re.compile(
    r"아마|같아|같습|일\s*수|가정|예를\s*들|예시|이면|이라면|가요|나요|까요|어떻게|예상|추정|\?"
    r"|\b(?:maybe|perhaps|might|could|if|example)\b",
    re.IGNORECASE,
)
UNKNOWN_FORM = re.compile(r"(?:현재\s*)?(?:형태|모양).{0,15}(?:모르|모름|미확인|불명)")
UNKNOWN_SUFFIX = re.compile(r"^\s*(?:인지|인지는|여부는).{0,8}(?:모르|모름|미확인|불명)")
NON_CURRENT = re.compile(
    r"예정|계획|할\s*거|하려|할\s*겁|과거|예전|이전에는|전에는|원래는"
    r"|\b(?:will|plan|previously|used to|going to)\b",
    re.IGNORECASE,
)
NEGATIVE_EN = re.compile(r"\b(?:not|no|without|never)\b", re.IGNORECASE)
NEGATED = re.compile(r"^\s*(?:(?:이|가|은|는|도|을|를|이란|형태)\s*)?(?:아니|아닙|아님|아닌|없)")


def timestamp(value):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result if result.tzinfo is not None else None
    except (ValueError, AttributeError, TypeError):
        return None


def inherited_form(detail):
    """No broad guessing: ambiguous/history-only statements require a user selection."""
    handoff = detail.get("handoff") or {}
    fact = (handoff.get("facts") or {}).get("input_form")
    if isinstance(fact, dict):
        form = normalize_form(fact.get("value")) if isinstance(fact.get("value"), str) else None
        if form and fact.get("status") not in {"UNKNOWN", "DECLARED_UNKNOWN", "UNVERIFIED"}:
            return {"value": form, "source": "handoff", "quote": None, "turn_id": None}
        return None
    reopened = [timestamp(v.get("reopened_at")) for v in detail.get("verdicts", [])]
    cutoff = max((v for v in reopened if v), default=None)
    confirmed = timestamp((handoff.get("timestamps") or {}).get("confirmed_at"))
    rows = detail.get("conversation") or []
    if not rows and not cutoff and detail.get("case", {}).get("memo"):
        rows = [{"role": "user", "text": detail["case"]["memo"]}]
    matches = []
    blocked = False
    for row in rows:
        if row.get("role") != "user" or row.get("quick_reply") or row.get("document_id"):
            continue
        at = timestamp(row.get("at"))
        if (cutoff and (not at or at < cutoff)) or (confirmed and at and at > confirmed):
            continue
        for clause in re.split(r"[.!。\n;]+", str(row.get("text") or "")):
            spans = [
                (form, m)
                for form, pattern in FORM_WORDS.items()
                for m in re.finditer(pattern, clause, re.IGNORECASE)
            ]
            if not spans:
                if UNKNOWN_FORM.search(clause):
                    blocked = True
                continue
            if (
                UNCERTAIN.search(clause)
                or UNKNOWN_FORM.search(clause)
                or any(UNKNOWN_SUFFIX.search(clause[m.end() :]) for _, m in spans)
            ):
                blocked = True
                continue
            transport_plan = re.search(r"보내|보낼|반출|위탁|운송|배송|인계", clause)
            conversion_plan = re.search(
                r"만들|가공|변환|압축할|파쇄할|분쇄할|세척할|감용할", clause
            )
            if NON_CURRENT.search(clause) and (not transport_plan or conversion_plan):
                blocked = True
                continue
            if NEGATIVE_EN.search(clause) or any(
                NEGATED.search(clause[m.end() :]) for _, m in spans
            ):
                blocked = True
                continue
            forms = {f for f, _ in spans}
            # These describe the same object, rather than two alternative forms.
            if "film-bale" in forms:
                forms -= {"film", "bale"}
            if "buoy" in forms:
                forms.discard("foam")
            matches.extend(
                {
                    "value": form,
                    "source": "conversation",
                    "quote": clause.strip()[:400],
                    "turn_id": row.get("turn_id"),
                }
                for form in forms
            )
    if blocked or len({m["value"] for m in matches}) != 1:
        return None
    return matches[-1]
