from fastapi import APIRouter

from app.domains.auth.router import router as auth_router
from app.domains.companies.router import router as companies_router
from app.domains.documents.router import router as documents_router
from app.domains.results.router import router as results_router
from app.domains.reviews.router import router as reviews_router
from app.domains.risks.router import router as risks_router
from app.domains.runs.router import router as runs_router
from app.domains.supplements.router import router as supplements_router
from app.domains.users.router import router as users_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(companies_router)
api_router.include_router(reviews_router)
api_router.include_router(documents_router)
api_router.include_router(runs_router)
api_router.include_router(results_router)
api_router.include_router(risks_router)
api_router.include_router(supplements_router)
