"""Public high-level SIP client."""

from __future__ import annotations

import logging
from threading import RLock
from uuid import UUID

from src.adapters.base import AccountBackend, CallBackend, SipBackendFactory
from src.adapters.pjsip import PjsipBackendFactory

from .config import SipConfig
from .core.call_manager import CallManager
from .core.call_session import CallSession
from .core.engine import SipEngine
from .core.events import EventDispatcher, EventHandler, EventType
from .exceptions import SipCallError, SipError, SipRegistrationError, SipStateError

__all__ = ["SipClient"]
logger = logging.getLogger(__name__)


class SipClient:
    def __init__(self, config: SipConfig, *, backend_factory: SipBackendFactory | None = None, dispatcher: EventDispatcher | None = None) -> None:
        self.config = config
        self._dispatcher = dispatcher or EventDispatcher()
        self._backend_factory = backend_factory or PjsipBackendFactory(self._dispatcher.publish)
        self._endpoint = self._backend_factory.create_endpoint(config)
        self._engine = SipEngine(self._endpoint, config.engine_config)
        self._account: AccountBackend | None = None
        self._calls = CallManager(self._engine, self._dispatcher, self._create_call_backend)
        self._lock = RLock()
        self._closed = False

    @property
    def is_running(self) -> bool:
        return self._engine.is_running

    @property
    def dispatcher(self) -> EventDispatcher:
        return self._dispatcher

    def start(self) -> None:
        with self._lock:
            if self._closed:
                raise SipStateError("SIP client has been closed and cannot be restarted")
            if self.is_running:
                return
            self._engine.start()
            try:
                self._account = self._backend_factory.create_account(self._endpoint, self.config)
                start = getattr(self._account, "start", None)
                if callable(start):
                    start()
            except Exception as exc:
                self._account = None
                try:
                    self._engine.stop()
                except SipError:
                    logger.exception("Endpoint cleanup after failed account setup failed")
                raise SipRegistrationError("Failed to start SIP account") from exc
        logger.info("SIP client started host=%s user=%s", self.config.host, self.config.username)

    def call(self, destination: str) -> CallSession:
        if not self.is_running or self._closed:
            raise SipStateError("Start SIP client before creating calls")
        return self._calls.create_call(self.config.destination_uri(destination))

    def get_call(self, call_id: UUID) -> CallSession | None:
        return self._calls.get_call(call_id)

    def active_calls(self) -> tuple[CallSession, ...]:
        return self._calls.active_calls()

    def poll(self, timeout_ms: int | None = None) -> int:
        return self._engine.poll(timeout_ms)

    def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        self._dispatcher.subscribe(event_type, handler)

    def unsubscribe(self, event_type: EventType, handler: EventHandler) -> None:
        self._dispatcher.unsubscribe(event_type, handler)

    def stop(self) -> None:
        with self._lock:
            if self._closed:
                return
            try:
                self._calls.close()
            finally:
                try:
                    if self._account is not None:
                        try:
                            self._account.close()
                        finally:
                            self._account = None
                finally:
                    try:
                        self._engine.stop()
                    finally:
                        self._closed = True
        logger.info("SIP client stopped")

    close = stop

    def __enter__(self) -> "SipClient":
        self.start()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.stop()

    def _create_call_backend(self, call_id: UUID) -> CallBackend:
        if self._account is None:
            raise SipStateError("SIP account is not started")
        return self._account.create_call(str(call_id))
