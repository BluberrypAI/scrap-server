from fastapi import APIRouter, Response

from app.core.errors import NotFoundError
from app.db.session import DbSession
from app.domains.auth.dependencies import CurrentUser
from app.domains.companies import service as company_service
from app.domains.transport import supplier_policy
from app.domains.transport.schemas import PolicyWrite, SupplierPolicyRead, SupplierSiteRead

router = APIRouter(prefix="/workflow", tags=["transport"])


async def company_id(db, user):
    company = await company_service.get_company_by_user(db, user.id)
    if company is None:
        raise NotFoundError("등록된 기업이 없음")
    return company.id


@router.get("/supplier-policies", response_model=list[SupplierSiteRead])
async def my_policies(user: CurrentUser, db: DbSession, response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    return await supplier_policy.my_policies(db, await company_id(db, user))


@router.post("/supplier-policies", response_model=SupplierPolicyRead)
async def save_policy(body: PolicyWrite, user: CurrentUser, db: DbSession):
    return await supplier_policy.save_policy(db, await company_id(db, user), body)
