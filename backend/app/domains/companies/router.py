import math

from fastapi import APIRouter, Query, Response, status

from app.core.config import get_settings
from app.core.errors import AppError, ConflictError, ErrorCode, NotFoundError
from app.db.session import DbSession
from app.domains.auth.dependencies import CurrentUser, RegularUser
from app.domains.companies import geocoding, service
from app.domains.companies.models import Company
from app.domains.companies.schemas import (
    CompanyCreate,
    CompanyHistoryItem,
    CompanyHistoryPage,
    CompanyRead,
    CompanyUpdate,
    CompanyUpdateResult,
    LocationSearch,
    LocationSearchResult,
    PagingInfo,
)
from app.domains.users.models import User

router = APIRouter(prefix="/companies", tags=["companies"])


async def _my_company(user: User, db: DbSession) -> Company:
    company = await service.get_company_by_user(db, user.id)
    if company is None:
        raise NotFoundError("등록된 기업이 없음")
    return company


@router.post("", response_model=CompanyRead, status_code=status.HTTP_201_CREATED)
async def create_company(data: CompanyCreate, user: CurrentUser, db: DbSession) -> CompanyRead:
    try:
        company = await service.create_company(db, user.id, data)
    except service.CompanyAlreadyExistsError:
        raise ConflictError(ErrorCode.COMPANY_ALREADY_EXISTS, "이미 등록된 기업이 있음") from None
    return CompanyRead.from_company(company)


@router.get("/me", response_model=CompanyRead)
async def read_my_company(user: CurrentUser, db: DbSession) -> CompanyRead:
    return CompanyRead.from_company(await _my_company(user, db))


@router.patch(
    "/me",
    response_model=CompanyUpdateResult,
    summary="내 기업 정보 수정",
    description="보낸 필드만 바꿈 (company_name, contact_email, industry, site_name, "
    "site_address, site_facilities, main_products, main_waste_types). 목록 필드는 통째로 "
    "교체함. 값이 바뀌면 profile_version이 1 오르고 변경 이력이 남음. "
    "profile_version이 현재 버전과 다르면 409.",
    responses={409: {"description": "다른 곳에서 먼저 수정됨 (profile_version 불일치)"}},
)
async def update_my_company(
    data: CompanyUpdate, user: RegularUser, db: DbSession
) -> CompanyUpdateResult:
    company = await _my_company(user, db)
    try:
        changed = await service.update_company(db, company, data)
    except service.VersionConflictError:
        raise ConflictError(
            ErrorCode.VERSION_CONFLICT, "다른 곳에서 먼저 수정됨. 다시 조회한 뒤 수정해야 함"
        ) from None
    return CompanyUpdateResult(profile_version=company.profile_version, changed_fields=changed)


@router.get(
    "/me/history",
    response_model=CompanyHistoryPage,
    summary="내 기업 정보 변경 이력",
    description="최신 버전부터 반환함. pageNumber는 1부터 시작함.",
)
async def read_my_company_history(
    user: CurrentUser,
    db: DbSession,
    page_number: int = Query(1, alias="pageNumber", ge=1),
    page_size: int = Query(20, alias="pageSize", ge=1, le=100),
) -> CompanyHistoryPage:
    company = await _my_company(user, db)
    rows, total = await service.list_history(db, company.id, page_number, page_size)
    total_pages = math.ceil(total / page_size)
    return CompanyHistoryPage(
        items=[CompanyHistoryItem.model_validate(row) for row in rows],
        paging_info=PagingInfo(
            current_page_number=page_number,
            page_size=page_size,
            element_count=total,
            total_page_count=total_pages,
            is_last_page=page_number >= total_pages,
            is_empty=not rows,
        ),
    )


@router.post("/location-search", response_model=LocationSearchResult)
async def search_site_location(data: LocationSearch, user: CurrentUser, response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    try:
        return await geocoding.search_location(data.query, get_settings())
    except geocoding.GeocodingBusy:
        raise AppError(
            429,
            ErrorCode.PROVIDER_UNAVAILABLE,
            "검색 요청이 많아요. 잠시 후 다시 검색해 주세요.",
            headers={"Retry-After": "2"},
        ) from None
    except geocoding.GeocodingUnavailable:
        raise AppError(
            503,
            ErrorCode.PROVIDER_UNAVAILABLE,
            "주소 검색에 연결하지 못했어요. 잠시 후 재시도하거나 지도에서 위치를 지정해 주세요.",
        ) from None
