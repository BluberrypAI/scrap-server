"""검토 실행 워커.

지금은 API 프로세스 안에서 asyncio 작업으로 실행함. 요구사항(NFR-6, Service Bus + 별도 워커 파드)에
맞추려면 RunQueue를 Service Bus에 넣는 구현으로 바꾸고, 워커 파드가 execute_run을 호출하면 됨.
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domains.runs import stages
from app.domains.runs.engine_client import EngineClient, EngineError
from app.domains.runs.models import Run, RunErrorCode, RunStatus

logger = logging.getLogger(__name__)


def _fail(run: Run, code: RunErrorCode, message: str) -> None:
    run.status = RunStatus.FAILED
    run.error_code = code
    run.error_message = message[:500]
    run.stages = stages.with_stage(run.stages, stages.RESEARCH, "failed", message[:200])
    run.finished_at = datetime.now(UTC)


def _complete(run: Run, result: dict) -> None:
    coverage = result.get("coverage") or {}
    complete = coverage.get("all_pages_read") is True
    route = result.get("route")
    run.result = result
    run.router_state = route
    run.status = RunStatus.COMPLETED if complete else RunStatus.PARTIAL
    research_reason = None if complete else "조회 한도 안에서 전체 후보를 다 읽지 못함"
    run.stages = stages.with_stage(
        run.stages, stages.RESEARCH, "done" if complete else "limit_reached", research_reason
    )
    run.stages = stages.with_stage(run.stages, stages.ROUTER, "done", f"엔진 판정: {route}")
    run.pinned_versions = {
        **run.pinned_versions,
        "engine_contract_version": result.get("contract_version"),
        "engine_run_id": result.get("run_id"),
        "request_sha256": result.get("request_sha256"),
        "graph_trace": result.get("graph_trace"),
    }
    run.finished_at = datetime.now(UTC)


async def execute_run(
    run_id: uuid.UUID,
    session_factory: async_sessionmaker[AsyncSession],
    engine: EngineClient,
) -> None:
    async with session_factory() as db:
        run = await db.get(Run, run_id)
        if run is None or run.status != RunStatus.QUEUED:
            return
        run.status = RunStatus.RUNNING
        run.started_at = datetime.now(UTC)
        run.stages = stages.with_stage(run.stages, stages.RESEARCH, "running")
        await db.commit()

        try:
            result = await engine.research(run.lot)
        except EngineError as exc:
            _fail(run, exc.code, exc.message)
        except Exception:
            logger.exception("Run %s failed", run_id)
            _fail(run, RunErrorCode.INTERNAL_ERROR, "실행 중 서버 오류가 발생함")
        else:
            _complete(run, result)
        await db.commit()


class InProcessRunQueue:
    """같은 프로세스에서 바로 실행함. 프로세스가 죽으면 진행 중 실행은 WORKER_INTERRUPTED가 됨."""

    def __init__(self) -> None:
        # 실행 중 작업이 가비지 컬렉션되지 않게 참조를 들고 있음
        self._tasks: set[asyncio.Task[None]] = set()

    async def enqueue(
        self,
        run_id: uuid.UUID,
        session_factory: async_sessionmaker[AsyncSession],
        engine: EngineClient,
    ) -> None:
        task = asyncio.create_task(execute_run(run_id, session_factory, engine))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)


_queue = InProcessRunQueue()


def get_run_queue() -> InProcessRunQueue:
    return _queue
