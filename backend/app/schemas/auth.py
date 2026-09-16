from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int


class ConfirmRequest(BaseModel):
    """Tweede bevestiging voor gevoelige handelingen."""

    password: str = Field(min_length=1)


class ConfirmationResponse(BaseModel):
    confirmation_token: str
    expires_in_minutes: int


class UserOut(BaseModel):
    id: int
    email: str
    display_name: str
    tier: int
    permissions: list[str]
