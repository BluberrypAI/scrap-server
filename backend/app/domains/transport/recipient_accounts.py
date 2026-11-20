"""Resolve live recipient accounts without invalidating cached process/AI evidence."""

from copy import deepcopy

from sqlalchemy import select

from app.core.config import get_settings
from app.domains.companies.models import Company
from app.domains.transport.models import WorkflowFacilityAccount


async def with_current_recipients(db, review):
    if review is None:
        return None
    response = deepcopy(review)
    facilities = [
        facility
        for option in response.get("next_step", {}).get("options", [])
        for facility in option.get("facilities", [])
    ]
    keys = {facility["facility_key"] for facility in facilities}
    if not keys:
        return response
    bindings = {
        binding.facility_key: binding
        for binding in await db.scalars(
            select(WorkflowFacilityAccount).where(WorkflowFacilityAccount.facility_key.in_(keys))
        )
        if not binding.synthetic or get_settings().synthetic_bindings_allowed
    }
    companies = {
        company.id: company
        for company in await db.scalars(
            select(Company).where(Company.id.in_({b.company_id for b in bindings.values()}))
        )
    }
    for facility in facilities:
        binding = bindings.get(facility["facility_key"])
        company = companies.get(binding.company_id) if binding else None
        facility["recipient"] = (
            {"id": str(company.id), "name": company.company_name, "synthetic": binding.synthetic}
            if company and str(company.id) != response.get("origin_company_id")
            else None
        )
    return response
