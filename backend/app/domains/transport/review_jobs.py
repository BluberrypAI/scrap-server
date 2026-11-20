"""DB-persisted review work and progress, with short HTTP requests and lease recovery."""

import asyncio
import logging
import uuid
from copy import deepcopy
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text

from app.core.errors import AppError
from app.db.session import get_session_factory
from app.domains.diagnosis.client import get_engine_client
from app.domains.transport.models import WorkflowLot
from app.domains.treatment.progressive import ReviewUnavailable

logger = logging.getLogger(__name__)
ACTIVE = {"queued", "running"}
LEASE_SECONDS = 150


class ObsoleteReview(RuntimeError):
    pass


def enqueue(lot):
    previous = lot.data.get("review_job", {})
    if previous.get("status") in ACTIVE and previous.get("revision") == lot.revision:
        return previous
    job = {
        "id": str(uuid.uuid4()),
        "status": "queued",
        "phase": "queued",
        "revision": lot.revision,
        "company_id": str(lot.current_company_id),
        "completed": 0,
        "total": 0,
        "selected": 0,
        "target": 5,
        "model_calls": 0,
        "cache_hits": 0,
        "started_at": datetime.now(UTC).isoformat(),
    }
    lot.data = {**lot.data, "review_job": job}
    return job


async def claim(factory):
    async with factory() as db:
        if db.get_bind().dialect.name == "postgresql":
            acquired = await db.scalar(
                text("SELECT pg_try_advisory_xact_lock(hashtext('scrap_review_jobs'))")
            )
            if not acquired:
                return None
        # A single lease across server replicas bounds the total treatment-review load.
        running = list(
            await db.scalars(
                select(WorkflowLot)
                .where(WorkflowLot.data["review_job"]["status"].as_string() == "running")
                # A heartbeat may hold this row briefly. Skipping it could hide
                # the active lease and incorrectly start a second job.
                .with_for_update()
            )
        )
        now = datetime.now(UTC)
        live = False
        for lot in running:
            job = deepcopy(lot.data["review_job"])
            lease = datetime.fromisoformat(job["lease_until"])
            if lease > now:
                live = True
            else:
                job.update(
                    status="interrupted",
                    phase="interrupted",
                    message="검토가 중단됐어요. 완료된 결과를 유지하고 다시 시도할 수 있어요.",
                )
                lot.data = {**lot.data, "review_job": job}
        if live:
            await db.commit()
            return None
        lot = await db.scalar(
            select(WorkflowLot)
            .where(WorkflowLot.data["review_job"]["status"].as_string() == "queued")
            .order_by(WorkflowLot.updated_at, WorkflowLot.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if lot is None:
            await db.commit()
            return None
        job = deepcopy(lot.data["review_job"])
        if job["revision"] != lot.revision or job["company_id"] != str(lot.current_company_id):
            job.update(status="cancelled", phase="cancelled")
        else:
            job.update(
                status="running",
                phase="candidate_search",
                lease_until=(now + timedelta(seconds=LEASE_SECONDS)).isoformat(),
            )
        lot.data = {**lot.data, "review_job": job}
        key = lot.id
        await db.commit()
        return (key, job) if job["status"] == "running" else None


async def update(
    factory,
    key,
    job_id,
    *,
    phase=None,
    status=None,
    cache=None,
    message=None,
    check_revision=True,
    **values,
):
    async with factory() as db:
        lot = await db.scalar(
            select(WorkflowLot)
            .where(WorkflowLot.id == key)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        job = deepcopy((lot.data if lot else {}).get("review_job", {}))
        if (
            not job
            or job.get("id") != job_id
            or (
                check_revision
                and (
                    job["revision"] != lot.revision
                    or job["company_id"] != str(lot.current_company_id)
                )
            )
        ):
            raise ObsoleteReview()
        job.update(values)
        job["lease_until"] = (datetime.now(UTC) + timedelta(seconds=LEASE_SECONDS)).isoformat()
        if phase:
            if phase != job.get("phase"):
                job["phase_history"] = (
                    job.get("phase_history", [])
                    + [{"phase": phase, "at": datetime.now(UTC).isoformat()}]
                )[-20:]
            job["phase"] = phase
        if status:
            job["status"] = status
        if message:
            job["message"] = message
        data = {**lot.data, "review_job": job}
        if cache is not None:
            data["_review_cache"] = deepcopy(cache)
        lot.data = data
        await db.commit()


async def run_next(factory=None, engine=None):
    from app.domains.transport.workflow import Version, run_candidate_review

    factory = factory or get_session_factory()
    work = await claim(factory)
    if work is None:
        return False
    key, job = work

    async def report(phase, **values):
        await update(factory, key, job["id"], phase=phase, **values)

    async def heartbeat():
        while True:
            await asyncio.sleep(25)
            await update(factory, key, job["id"])

    pulse = asyncio.create_task(heartbeat())
    try:
        async with factory() as db:
            await run_candidate_review(
                key,
                Version(revision=job["revision"]),
                job["company_id"],
                db,
                engine or get_engine_client(),
                progressive=True,
                report=report,
            )
        await update(
            factory, key, job["id"], status="completed", phase="completed", check_revision=False
        )
    except asyncio.CancelledError:
        await update(
            factory, key, job["id"], status="interrupted", phase="interrupted", check_revision=False
        )
        raise
    except (ObsoleteReview, AppError, ReviewUnavailable) as error:
        message = (
            str(error)
            if isinstance(error, ReviewUnavailable)
            else "입력 또는 문진 결과를 확인하고 검토를 다시 시도해 주세요."
        )
        try:
            await update(
                factory,
                key,
                job["id"],
                status="failed",
                phase="failed",
                message=message,
                check_revision=False,
            )
        except ObsoleteReview:
            pass
    except Exception:
        # Keep provider text and inputs out of operational logs and browser errors.
        logger.error("candidate_review_job_failed reason=internal_error")
        try:
            await update(
                factory,
                key,
                job["id"],
                status="failed",
                phase="failed",
                message="검토를 완료하지 못했어요. 다시 시도해 주세요.",
                check_revision=False,
            )
        except ObsoleteReview:
            pass
    finally:
        pulse.cancel()
        await asyncio.gather(pulse, return_exceptions=True)
    return True


async def worker():
    while True:
        try:
            found = await run_next()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("candidate_review_worker_wait reason=storage_unavailable")
            found = False
        if not found:
            await asyncio.sleep(1)
