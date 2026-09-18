from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, model_validator


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)
    device_name: str | None = Field(
        default=None,
        max_length=120,
        description="Hoe dit apparaat in je lijst komt te staan, bijvoorbeeld "
        "'Telefoon van Stef'. Een geheugensteuntje, verder niets.",
    )


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int
    # Alleen bij inloggen met een wachtwoord. Een stemherkenning levert er geen: een opname
    # mag nooit een sessie van twee maanden worden.
    refresh_token: str | None = None
    session_id: int | None = None


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class SessionOut(BaseModel):
    """Eén ingelogd apparaat. Zonder tokens — die staan hier met opzet niet in."""

    id: int
    device_name: str | None
    user_agent: str | None
    ip_address: str | None
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime
    # Of dit het apparaat is waar je nu op kijkt. Handig als je er vijf hebt.
    current: bool = False


class RevokeResponse(BaseModel):
    revoked: int
    message: str


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
    # Alleen of er een pincode is, nooit de pincode zelf. De telefoon gebruikt dit om te
    # kiezen wat hij bij een bevestiging vraagt.
    has_pin: bool = False
