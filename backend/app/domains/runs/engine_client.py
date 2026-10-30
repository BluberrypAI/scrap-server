"""AI 엔진(ai 레포) HTTP 클라이언트.

계약: ai 레포 `POST /analysis/research` (src/resource_ai/api/schemas/analysis.py,
contract_version candidate-research-v1). 엔진은 동기 응답이라 실행 상태는 server가 관리함.
"""

import logging
from typing import Any

import httpx

from app.core.config import get_settings
from app.domains.runs.models import RunErrorCode

logger = logging.getLogger(__name__)

RESEARCH_CONTRACT = "candidate-research-v1"

# 엔진 lot 스키마(AssessedPlansRequest)가 받는 항목. extra="forbid"라 다른 키를 보내면 422
LOT_FIELDS = (
    "material",
    "input_form",
    "color",
    "contamination",
    "quantity_kg",
    "generation_process",
    "region",
    "current_treatment",
    "moisture_pct",
    "contamination_pct",
    "designated_waste",
)


class EngineError(Exception):
    def __init__(self, code: RunErrorCode, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class EngineClient:
    def __init__(
        self,
        base_url: str,
        timeout: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.base_url = base_url
        self.timeout = timeout
        self.transport = transport

    async def research(self, lot: dict[str, Any]) -> dict[str, Any]:
        """KG 후보 전체 조회 + 시설 공개 조건 대조 + 법령 검색. 실패하면 EngineError."""
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url, timeout=self.timeout, transport=self.transport
            ) as client:
                res = await client.post("/analysis/research", json={"lot": lot})
        except httpx.TimeoutException:
            raise EngineError(RunErrorCode.ENGINE_TIMEOUT, "AI 엔진 응답 시간 초과") from None
        except httpx.HTTPError as exc:
            logger.warning("AI engine request failed: %s", type(exc).__name__)
            raise EngineError(RunErrorCode.ENGINE_UNAVAILABLE, "AI 엔진에 연결할 수 없음") from None

        if res.status_code != 200:
            raise _status_error(res)
        body = res.json()
        if body.get("contract_version") != RESEARCH_CONTRACT:
            raise EngineError(
                RunErrorCode.ENGINE_CONTRACT_MISMATCH,
                f"AI 엔진 응답 형식이 다름 (기대: {RESEARCH_CONTRACT})",
            )
        return body


def _status_error(res: httpx.Response) -> EngineError:
    # 엔진 오류 본문은 {"detail": {"code", "message"}} 또는 FastAPI 검증 오류. 코드만 남김
    detail = _safe_json(res).get("detail")
    engine_code = detail.get("code") if isinstance(detail, dict) else None
    logger.warning("AI engine returned %s (%s)", res.status_code, engine_code)
    suffix = f" ({engine_code})" if engine_code else ""
    if res.status_code == 409:
        return EngineError(
            RunErrorCode.GRAPH_VERSION_CHANGED, "조회 중 지식그래프 버전이 바뀜. 다시 실행해야 함"
        )
    if res.status_code in (400, 422):
        return EngineError(RunErrorCode.ENGINE_REJECTED_INPUT, f"AI 엔진이 입력을 거절함{suffix}")
    return EngineError(
        RunErrorCode.ENGINE_UNAVAILABLE, f"AI 엔진 오류 HTTP {res.status_code}{suffix}"
    )


def _safe_json(res: httpx.Response) -> dict[str, Any]:
    try:
        body = res.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def get_engine_client() -> EngineClient | None:
    """AI_BASE_URL이 없으면 None. 테스트에서 교체함."""
    settings = get_settings()
    if not settings.ai_base_url:
        return None
    return EngineClient(settings.ai_base_url, settings.ai_timeout_seconds)
