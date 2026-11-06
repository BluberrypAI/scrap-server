"""응답을 바꿔 가며 쓰는 가짜 AI 엔진. 샘플 응답은 app/domains/runs/mock_engine.py에 있음."""

import json
import uuid
from collections.abc import Callable
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domains.runs.engine_client import EngineClient
from app.domains.runs.mock_engine import research_result
from app.domains.runs.worker import execute_run


class FakeEngine:
    """MockTransport로 엔진 응답을 흉내 냄. lots에 엔진이 받은 lot이 쌓임."""

    def __init__(self) -> None:
        self.lots: list[dict[str, Any]] = []
        self.respond: Callable[[], httpx.Response] = lambda: httpx.Response(
            200, json=research_result()
        )

    def _handler(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/analysis/research"
        self.lots.append(json.loads(request.content)["lot"])
        return self.respond()

    def client(self) -> EngineClient:
        return EngineClient("http://engine.test", 5, httpx.MockTransport(self._handler))


class InlineQueue:
    """요청 안에서 바로 실행함. enabled=False면 실행하지 않고 queued로 둠."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory
        self.enabled = True

    async def enqueue(self, run_id: uuid.UUID, session_factory, engine: EngineClient) -> None:
        if self.enabled:
            await execute_run(run_id, self.session_factory, engine)
