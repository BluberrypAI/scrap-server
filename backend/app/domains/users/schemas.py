import uuid

from pydantic import BaseModel


class UserRead(BaseModel):
    id: uuid.UUID
    email: str | None
    name: str | None
    has_company: bool
