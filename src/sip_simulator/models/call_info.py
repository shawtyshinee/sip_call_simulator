from .call_state import CallState
from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "CallInfo"
]


class CallInfo(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)
    call_info_id: str = Field(min_length=1)
    remote_uri: str = ""
    state: CallState
    sip_status_code: int | None = None
    sip_reason: str | None = None
