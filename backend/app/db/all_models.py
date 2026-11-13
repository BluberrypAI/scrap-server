"""Import every model module so Base.metadata is complete (used by Alembic and tests)."""

from app.db.base import Base
from app.domains.auth import models as auth_models  # noqa: F401
from app.domains.companies import models as companies_models  # noqa: F401
from app.domains.facilities import models as facilities_models  # noqa: F401
from app.domains.transport import models as transport_models  # noqa: F401
from app.domains.treatment import models as treatment_models  # noqa: F401
from app.domains.users import models as users_models  # noqa: F401
from app.domains.wastes import models as wastes_models  # noqa: F401

__all__ = ["Base"]
