from fastapi import APIRouter, HTTPException, status

from app.db.session import DbSession
from app.domains.auth.dependencies import CurrentUser
from app.domains.companies import service
from app.domains.companies.models import Company
from app.domains.companies.schemas import CompanyCreate, CompanyRead

router = APIRouter(prefix="/companies", tags=["companies"])


@router.post("", response_model=CompanyRead, status_code=status.HTTP_201_CREATED)
async def create_company(data: CompanyCreate, user: CurrentUser, db: DbSession) -> Company:
    try:
        return await service.create_company(db, user.id, data)
    except service.CompanyAlreadyExistsError:
        raise HTTPException(status.HTTP_409_CONFLICT, "Company already registered") from None


@router.get("/me", response_model=CompanyRead)
async def read_my_company(user: CurrentUser, db: DbSession) -> Company:
    company = await service.get_company_by_owner(db, user.id)
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Company not registered")
    return company
