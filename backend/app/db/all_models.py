"""Import every model module so Base.metadata is complete (used by Alembic and tests)."""

from app.db.base import Base
from app.domains.auth import models as auth_models  # noqa: F401
from app.domains.companies import models as companies_models  # noqa: F401
from app.domains.documents import models as documents_models  # noqa: F401
from app.domains.reviews import models as reviews_models  # noqa: F401
from app.domains.runs import models as runs_models  # noqa: F401
from app.domains.users import models as users_models  # noqa: F401

__all__ = ["Base"]
