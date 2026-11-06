import uuid
from copy import deepcopy
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import or_, select

from app.core.config import get_settings
from app.domains.transport.models import TransportHandoff, TransportSharedCase
from app.domains.treatment.schemas import ObservedOutput
from app.domains.users.models import User


async def recipient_for(db, facility_key):
    settings = get_settings()
    if settings.app_env not in {"local", "test"}:
        return None
    value = settings.transport_demo_facilities.get(facility_key)
    if not value:
        return None
    user = await db.get(User, uuid.UUID(value))
    return user.id if user and not user.is_withdrawn else None


async def lock_case(db, key):
    return await db.scalar(
        select(TransportSharedCase).where(TransportSharedCase.id == key).with_for_update()
    )


def pending_matches(snapshot, key, lot, destination):
    pending = snapshot.get("pending") or {}
    return (
        snapshot.get("version") == 1
        and snapshot.get("id") == lot
        and pending.get("legId") == str(key)
        and pending.get("facility") == destination
        and not snapshot.get("finished")
    )


async def prepare_registration(db, key, owner, data):
    update = data.case_update
    recipient = await recipient_for(db, data.destination_key)
    if not update or not recipient or recipient == owner:
        return None
    snap = update.snapshot
    if (
        not pending_matches(snap, key, data.lot, data.destination)
        or snap["pending"].get("facility_key") != data.destination_key
    ):
        return None
    if data.shared_case_id:
        case = await lock_case(db, data.shared_case_id)
        if (
            not case
            or case.active_id != owner
            or case.revision != update.revision
            or case.snapshot.get("pending")
            or case.snapshot.get("finished")
            or any(
                snap.get(field) != case.snapshot.get(field)
                for field in ("id", "input", "completed")
            )
        ):
            return None
        case.active_id = recipient
        case.snapshot = snap
        case.revision += 1
    else:
        if update.revision or snap["completed"]:
            return None
        case = TransportSharedCase(id=key, owner_id=owner, active_id=recipient, snapshot=snap)
        db.add(case)
        await db.flush()
    return case.id, recipient


async def case_view(db, case, user):
    if case.owner_id != user and not await db.scalar(
        select(TransportHandoff.id)
        .where(
            TransportHandoff.shared_case_id == case.id,
            or_(TransportHandoff.owner_id == user, TransportHandoff.recipient_id == user),
        )
        .limit(1)
    ):
        return None
    snapshot = deepcopy(case.snapshot)
    pending = snapshot.get("pending") or {}
    if pending.get("legId"):
        leg = await db.get(TransportHandoff, uuid.UUID(pending["legId"]))
        if leg and leg.receipt_at:
            pending["handoff"] = {
                "status": "accepted",
                "actor": leg.receipt_actor,
                "respondedAt": leg.receipt_at.isoformat(),
            }
        if leg and leg.pickup_at:
            pending["pickup"] = {
                "actor": leg.pickup_actor,
                "respondedAt": leg.pickup_at.isoformat(),
            }
    return {
        "id": case.id,
        "revision": case.revision,
        "can_process": case.active_id == user,
        "snapshot": snapshot,
    }


async def inbox(db, user):
    records = await db.scalars(
        select(TransportSharedCase)
        .where(
            or_(
                TransportSharedCase.owner_id == user,
                TransportSharedCase.id.in_(
                    select(TransportHandoff.shared_case_id).where(
                        TransportHandoff.recipient_id == user
                    )
                ),
            )
        )
        .order_by(TransportSharedCase.updated_at.desc())
        .limit(100)
    )
    return [
        {
            "id": case.id,
            "lot": case.snapshot["id"],
            "name": case.snapshot["name"],
            "can_process": case.active_id == user,
        }
        for case in records
    ]


async def update_case(db, key, user, data):
    case = await lock_case(db, key)
    if not case or case.active_id != user or case.revision != data.revision:
        return None
    before, after = case.snapshot, data.snapshot
    if before.get("finished") or any(
        before.get(k) != after.get(k) for k in ("version", "id", "input", "name")
    ):
        return None
    old_steps, new_steps = before["completed"], after["completed"]
    current = before.get("pending")
    if current and after.get("pending"):
        view = await case_view(db, case, user)
        if view is None:
            return None
        visible = view["snapshot"]["pending"]
        revised = dict(after["pending"])
        requested = revised.pop("outputUnconfirmedAt", None)
        visible.pop("outputUnconfirmedAt", None)
        if (
            not requested
            or after.get("finished")
            or new_steps != old_steps
            or revised != visible
            or not (
                visible.get("internal")
                or (visible.get("handoff") or {}).get("status") == "accepted"
            )
        ):
            return None
        after["pending"]["outputUnconfirmedAt"] = datetime.now(UTC).isoformat()
    elif current:
        if after.get("pending") or after.get("finished") or len(new_steps) != len(old_steps) + 1:
            return None
        if new_steps[:-1] != old_steps or not isinstance(new_steps[-1], dict):
            return None
        if any(
            new_steps[-1].get(k) != current.get(k)
            for k in ("legId", "transition_key", "facility_key", "expectedState")
        ):
            return None
        if not current.get("internal"):
            leg = await db.get(TransportHandoff, uuid.UUID(current["legId"]))
            if not leg or not leg.receipt_at:
                return None
            new_steps[-1]["handoff"] = {
                "status": "accepted",
                "actor": leg.receipt_actor,
                "respondedAt": leg.receipt_at.isoformat(),
            }
    elif old_steps:
        if after.get("pending") and (
            not after["pending"].get("internal") or new_steps != old_steps
        ):
            return None
        if len(new_steps) != len(old_steps) or new_steps[:-1] != old_steps[:-1]:
            return None
        original, revised = deepcopy(old_steps[-1]), deepcopy(new_steps[-1])
        if not isinstance(original, dict) or not isinstance(revised, dict):
            return None
        if (
            not original.get("observedOutput")
            and revised.get("observedOutput") is not None
            and not after.get("pending")
            and not after.get("finished")
        ):
            try:
                observed = ObservedOutput.model_validate(revised["observedOutput"])
            except ValidationError:
                return None
            label = revised.get("observedLabel")
            if observed.review_reference is not None or not isinstance(label, str) or not label:
                return None
            for step in (original, revised):
                step.pop("observedOutput", None)
                step.pop("observedLabel", None)
        old_output, new_output = original.get("observedOutput"), revised.get("observedOutput")
        if (
            isinstance(old_output, dict)
            and isinstance(new_output, dict)
            and not after.get("pending")
            and not after.get("finished")
        ):
            additions = [
                key
                for key in ("mass_kg", "purity_percent")
                if old_output.get(key) is None and new_output.get(key) is not None
            ]
            if additions:
                try:
                    ObservedOutput.model_validate(new_output)
                except ValidationError:
                    return None
                for key in additions:
                    old_output.pop(key, None)
                    new_output.pop(key)
        for step in (original, revised):
            if step.get("observedOutput"):
                step["observedOutput"].pop("review_reference", None)
        if original != revised:
            return None
        if after.get("finished"):
            step = new_steps[-1]
            observed = step.get("observedOutput") or {}
            if (
                not observed.get("state_key")
                or observed.get("mass_kg") == 0
                or (
                    observed["state_key"] != (step.get("expectedState") or {}).get("key")
                    and not str(observed.get("review_reference") or "").strip()
                )
            ):
                return None
    else:
        return None
    case.snapshot = after
    case.revision += 1
    await db.commit()
    return await case_view(db, case, user)
