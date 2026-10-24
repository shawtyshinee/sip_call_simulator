"""Configuration models for the public SDK."""

from __future__ import annotations

import logging
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from .core.engine import EngineConfig
from .exceptions import SipConfigurationError

__all__ = ["SipConfig", "SipTransport"]


class SipTransport(str, Enum):
    UDP = "udp"
    TCP = "tcp"
    TLS = "tls"


class SipConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    host: str = Field(min_length=1)
    username: str = Field(min_length=1)
    password: SecretStr = Field(repr=False)
    port: int = Field(default=5060, ge=1, le=65535)
    transport: SipTransport = SipTransport.UDP
    register_account: bool = True
    local_port: int = Field(default=0, ge=0, le=65535)
    call_timeout: float = Field(default=15.0, gt=0, le=3600)
    event_poll_ms: int = Field(default=50, ge=0, le=1000)
    log_level: int = Field(default=logging.INFO, ge=0, le=50)

    @field_validator("host", "username")
    @classmethod
    def validate_sip_identifier(cls, value: str) -> str:
        if any(char.isspace() for char in value):
            raise ValueError("SIP host and username must not contain whitespace")
        return value

    @property
    def engine_config(self) -> EngineConfig:
        return EngineConfig(local_port=self.local_port, event_poll_ms=self.event_poll_ms, log_level=self.log_level)

    @property
    def account_uri(self) -> str:
        return f"sip:{self.username}@{self.host}"

    @property
    def registrar_uri(self) -> str:
        return f"sip:{self.host}:{self.port}"

    def destination_uri(self, destination: str) -> str:
        value = destination.strip()
        if not value:
            raise SipConfigurationError("destination must not be empty")
        if value.lower().startswith(("sip:", "sips:")):
            return value
        if any(char.isspace() for char in value):
            raise SipConfigurationError("destination must not contain whitespace")
        return f"sip:{value}@{self.host}"
