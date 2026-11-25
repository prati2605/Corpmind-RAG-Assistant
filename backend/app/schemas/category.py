from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import Role


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    description: str | None
    created_at: datetime


class CategoryWithRoles(CategoryOut):
    roles: list[Role]


class CategoryCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    description: str | None = Field(default=None, max_length=255)
    roles: list[Role] = Field(default_factory=list, description="Roles (besides admin) that can read this category")


class CategoryRolesUpdate(BaseModel):
    roles: list[Role]
