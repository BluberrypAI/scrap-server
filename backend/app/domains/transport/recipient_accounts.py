"""Resolve live recipient accounts without invalidating cached process/AI evidence."""

from copy import deepcopy
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.config import get_settings
from app.domains.companies.models import Company
from app.domains.transport.models import WorkflowFacilityAccount, WorkflowInquiryReplyLink


async def current_recipients(db, lot, facilities):
    keys = {facility["facility_key"] for facility in facilities}
    if not keys:
        return {}
    bindings = {
        binding.facility_key: binding
        for binding in await db.scalars(
            select(WorkflowFacilityAccount).where(WorkflowFacilityAccount.facility_key.in_(keys))
        )
    }
    guest_keys = {
        facility["capability_key"]
        for facility in facilities
        if facility["facility_key"] not in bindings
    }
    guests = {}
    if guest_keys:
        guests = dict(
            (
                await db.execute(
                    select(
                        WorkflowInquiryReplyLink.capability_key,
                        WorkflowInquiryReplyLink.guest_company_id,
                    ).where(
                        WorkflowInquiryReplyLink.lot_id == lot.id,
                        WorkflowInquiryReplyLink.company_id == lot.current_company_id,
                        WorkflowInquiryReplyLink.stage == len(lot.data["completed"]),
                        WorkflowInquiryReplyLink.capability_key.in_(guest_keys),
                        WorkflowInquiryReplyLink.guest_company_id.is_not(None),
                        WorkflowInquiryReplyLink.revoked_at.is_(None),
                        WorkflowInquiryReplyLink.expires_at > datetime.now(UTC),
                    )
                )
            ).all()
        )
    company_ids = {b.company_id for b in bindings.values()} | set(guests.values())
    if not company_ids:
        return {}
    companies = {
        company.id: company
        for company in await db.scalars(select(Company).where(Company.id.in_(company_ids)))
    }
    recipients = {}
    for facility in facilities:
        capability = facility["capability_key"]
        binding = bindings.get(facility["facility_key"])
        if binding and binding.synthetic and not get_settings().synthetic_bindings_allowed:
            continue
        company_id = binding.company_id if binding else guests.get(capability)
        company = companies.get(company_id)
        if company and company.id != lot.current_company_id:
            recipients[capability] = {
                "id": str(company.id),
                "name": company.company_name,
                "synthetic": binding.synthetic if binding else False,
                "guest": company.guest,
            }
    return recipients


async def with_current_recipients(db, lot):
    if lot.review is None:
        return None
    response = deepcopy(lot.review)
    facilities = [
        facility
        for option in response.get("next_step", {}).get("options", [])
        for facility in option.get("facilities", [])
    ]
    recipients = await current_recipients(db, lot, facilities)
    for facility in facilities:
        facility["recipient"] = recipients.get(facility["capability_key"])
    return response
