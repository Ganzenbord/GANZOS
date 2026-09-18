from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field, model_validator


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int


class SetPinRequest(BaseModel):
    password: str = Field(description="Je huidige wachtwoord")
    pin: str = Field(description="Vier tot twaalf cijfers")


class SetPinResponse(BaseModel):
    message: str


class ConfirmRequest(BaseModel):
    """Tweede bevestiging voor gevoelige handelingen.

    Eén van beide: je wachtwoord, of je pincode. De pincode is bedoeld voor de telefoon en
    voor bediening met de stem, waar een heel wachtwoord intikken onhandig is.
    """

    password: str | None = Field(default=None, min_length=1)
    pin: str | None = Field(default=None, min_length=1)
    permission_key: str | None = Field(
        default=None,
        description="Waarvoor je bevestigt, bijvoorbeeld 'upload.execute'. Vul je dit in, "
        "dan kan de bevestiging alleen voor díé handeling gebruikt worden.",
    )

    @model_validator(mode="after")
    def _precies_een(self) -> "ConfirmRequest":
        if bool(self.password) == bool(self.pin):
            raise ValueError("Geef je wachtwoord óf je pincode, niet allebei en niet geen van beide.")
        return self


class ConfirmationResponse(BaseModel):
    confirmation_token: str
    expires_in_minutes: int
    confirmation_id: int


class UserOut(BaseModel):
    id: int
    email: str
    display_name: str
    tier: int | None
    permissions: list[str]
