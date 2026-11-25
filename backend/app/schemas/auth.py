"""Request/response schemas for auth and users. Pydantic does input validation."""
import re
import uuid
from datetime import datetime

from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator

from app.models.enums import Role


_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-']+@[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?)+$")


def _check_email(v: str) -> str:
    """Syntax-only email check. Unlike EmailStr it accepts internal domains such as
    corp.local or company.internal, which are common in enterprises."""
    v = v.strip().lower()
    if len(v) > 254 or ".." in v or not _EMAIL_RE.match(v):
        raise ValueError("Invalid email address")
    return v


EmailStr = Annotated[str, Field(max_length=254), AfterValidator(_check_email)]


def _check_password_strength(v: str) -> str:
    if len(v) < 10:
        raise ValueError("Password must be at least 10 characters")
    if not (re.search(r"[A-Za-z]", v) and re.search(r"\d", v)):
        raise ValueError("Password must contain letters and numbers")
    return v


class RegisterRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=120)
    password: str = Field(max_length=128)
    department: str | None = Field(default=None, max_length=120)

    _pw = field_validator("password")(_check_password_strength)

    @field_validator("full_name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 2:
            raise ValueError("Name is too short")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(max_length=128)


class RefreshRequest(BaseModel):
    # Optional: browsers send it as an httpOnly cookie instead; API clients may send it in the body.
    refresh_token: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str
    role: Role
    department: str | None
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None


class MeOut(UserOut):
    accessible_categories: list[str]


class ProfileUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=120)
    department: str | None = Field(default=None, max_length=120)


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=128)
    new_password: str = Field(max_length=128)

    _pw = field_validator("new_password")(_check_password_strength)


class AdminUserUpdate(BaseModel):
    role: Role | None = None
    is_active: bool | None = None
    department: str | None = Field(default=None, max_length=120)


class AdminUserCreate(RegisterRequest):
    role: Role = Role.EMPLOYEE
