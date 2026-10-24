"""Lifecycle coordinator for an endpoint backend."""

from __future__ import annotations

import logging
from enum import Enum
from threading import RLock
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from ..exceptions import SipBackendError, SipConfigurationError, SipStateError

__all__ = ["EngineConfig", "EngineState", "EndpointBackend", "SipEngine"]
logger = logging.getLogger(__name__)


class EngineConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    local_port: int = Field(default=0, ge=0, le=65535)
    log_level: int = Field(default=logging.INFO, ge=0, le=50)
    event_poll_ms: int = Field(default=50, ge=0, le=1000)


class EngineState(str, Enum):
    STOPPED = "stopped"
    RUNNING = "running"


class EndpointBackend(Protocol):
    def start(self) -> None: ...
    def poll(self, timeout_ms: int = 50) -> int: ...
    def stop(self) -> None: ...


class SipEngine:
    def __init__(self, backend: EndpointBackend, config: EngineConfig | None = None) -> None:
        self._backend = backend
        self.config = config or EngineConfig()
        self._state = EngineState.STOPPED
        self._lock = RLock()

    @property
    def is_running(self) -> bool:
        return self._state is EngineState.RUNNING

    def start(self) -> None:
        with self._lock:
            if self.is_running:
                return
            try:
                self._backend.start()
            except Exception as exc:
                logger.exception("Failed to start SIP endpoint")
                raise SipBackendError("Failed to start SIP endpoint") from exc
            self._state = EngineState.RUNNING
        logger.info("SIP engine started")

    def poll(self, timeout_ms: int | None = None) -> int:
        if not self.is_running:
            raise SipStateError("SIP engine is not running")
        delay = self.config.event_poll_ms if timeout_ms is None else timeout_ms
        if delay < 0:
            raise SipConfigurationError("timeout_ms must be nonnegative")
        try:
            return self._backend.poll(delay)
        except Exception as exc:
            raise SipBackendError("Failed to process SIP events") from exc

    def stop(self) -> None:
        with self._lock:
            if not self.is_running:
                return
            try:
                self._backend.stop()
            except Exception as exc:
                raise SipBackendError("Failed to stop SIP endpoint") from exc
            finally:
                self._state = EngineState.STOPPED
        logger.info("SIP engine stopped")

    def __enter__(self) -> "SipEngine":
        self.start()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.stop()
