from enum import Enum
from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "RegistrationState",
    "SipAccount"
]

class RegistrationState(str, Enum):
    UNREGISTERED = "unregistered"
    REGISTERING = "registering"
    REGISTERED = "registered"
    FAILED = "failed"

class SipAccount(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)
    account_id: str = Field(min_length=1)
    uri: str = Field(min_length=1, pattern=r"^sips?:")
    registrar_uri: str | None = Field(default=None, pattern=r"^sips?:")
    registration_state: RegistrationState = RegistrationState.UNREGISTERED
    status_code: int | None = Field(default=None, ge=100, le=699)
    status_reason: str | None = None