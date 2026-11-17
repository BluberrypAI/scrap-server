from fastapi import APIRouter

from app.domains.auth.router import router as auth_router
from app.domains.companies.router import router as companies_router
from app.domains.diagnosis.router import router as diagnosis_router
from app.domains.transport.policy_router import router as supplier_policy_router
from app.domains.transport.router import router as transport_router
from app.domains.transport.workflow import router as workflow_router
from app.domains.users.router import router as users_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(companies_router)
api_router.include_router(diagnosis_router)
api_router.include_router(transport_router)
api_router.include_router(workflow_router)
api_router.include_router(supplier_policy_router)
