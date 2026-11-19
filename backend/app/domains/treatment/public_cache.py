"""Bounded public-evidence cache. Never stores company/lot declarations or photographs."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text

from app.domains.treatment.intake import IntakeResult
from app.domains.treatment.models import TreatmentSnapshot
from app.domains.treatment.reference import digest

KIND = "public-intake-cache-v1"
TTL = timedelta(days=7)
LIMIT = 1024
PUBLIC_FIELDS = (
    "capability_key",
    "site",
    "site_scope",
    "process",
    "waste_code",
    "material",
    "form",
    "recycling_types",
    "recycling_basis",
    "next_check",
    "sources",
)


def public_packet(packet):
    return {key: deepcopy(packet[key]) for key in PUBLIC_FIELDS if key in packet}


def cache_key(packet, signature):
    return digest({"packet": public_packet(packet), "signature": signature})


def public_finding(packet, result):
    source = next(
        (
            s
            for s in packet["sources"]
            if result.source
            and all(s[k] == getattr(result.source, k) for k in ("publisher", "url", "locator"))
        ),
        None,
    )
    return {
        "kind": result.finding,
        "source_id": source["source_id"] if source else None,
        "quote": result.quote,
        "evidence_gaps": result.evidence_gaps,
    }


class PublicReviewStore:
    def __init__(self, factory):
        self.factory = factory

    async def get_many(self, packets, signature):
        async with self.factory() as db:
            row = await db.get(TreatmentSnapshot, KIND)
            entries = row.payload if row else {}
            now, found = datetime.now(UTC), {}
            for packet in packets:
                entry = entries.get(cache_key(packet, signature), {})
                try:
                    if datetime.fromisoformat(entry["expires_at"]) > now:
                        result = IntakeResult.model_validate(entry["result"])
                        if (
                            result.status in {"reviewed", "needs_evidence"}
                            and result.lot_review is None
                        ):
                            found[packet["capability_key"]] = result
                except (KeyError, TypeError, ValueError):
                    continue
            return found

    async def put_many(self, packets, signature, results):
        now = datetime.now(UTC)
        additions = {}
        for packet in packets:
            result = results.get(packet["capability_key"])
            if (
                result is None
                or result.status not in {"reviewed", "needs_evidence"}
                or result.lot_review is not None
            ):
                continue
            # Only the independent public-only response may enter this shared store.
            value = result.model_dump(exclude={"lot_review"})
            additions[cache_key(packet, signature)] = {
                "checked_at": now.isoformat(),
                "expires_at": (now + TTL).isoformat(),
                "result": value,
            }
        if not additions:
            return
        async with self.factory() as db:
            if db.get_bind().dialect.name == "postgresql":
                await db.execute(
                    text("SELECT pg_advisory_xact_lock(hashtext('scrap_public_cache'))")
                )
            row = await db.scalar(
                select(TreatmentSnapshot).where(TreatmentSnapshot.kind == KIND).with_for_update()
            )
            entries = deepcopy(row.payload) if row else {}
            entries = {
                k: v for k, v in entries.items() if v.get("expires_at", "") > now.isoformat()
            }
            entries.update(additions)
            entries = dict(sorted(entries.items(), key=lambda pair: pair[1]["checked_at"])[-LIMIT:])
            if row:
                row.payload, row.checksum = entries, digest(entries)
            else:
                db.add(TreatmentSnapshot(kind=KIND, checksum=digest(entries), payload=entries))
            await db.commit()
