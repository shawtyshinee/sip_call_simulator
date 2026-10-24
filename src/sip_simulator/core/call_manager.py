"""Creation and ownership of active call sessions."""

from __future__ import annotations

import logging
from collections.abc import Callable
from threading import RLock
from uuid import UUID, uuid4

from ..exceptions import SipCallError, SipStateError
from .call_session import CallBackend, CallSession
from .engine import SipEngine
from .events import EventDispatcher, EventType, SipEvent

__all__ = ["CallBackendFactory", "CallManager"]
logger = logging.getLogger(__name__)
CallBackendFactory = Callable[[UUID], CallBackend]


class CallManager:
    def __init__(self, engine: SipEngine, dispatcher: EventDispatcher, backend_factory: CallBackendFactory) -> None:
        self._engine = engine
        self._dispatcher = dispatcher
        self._backend_factory = backend_factory
        self._calls: dict[UUID, CallSession] = {}
        self._lock = RLock()
        dispatcher.subscribe(EventType.CALL_STATE, self._on_call_state)

    def create_call(self, destination: str) -> CallSession:
        if not self._engine.is_running:
            raise SipStateError("Start SIP engine before creating calls")
        if not destination.strip():
            raise SipCallError("destination must not be empty")
        call_id = uuid4()
        try:
            backend = self._backend_factory(call_id)
            session = CallSession(call_id, destination, backend, self._engine, self._dispatcher)
            with self._lock:
                self._calls[call_id] = session
            session.start()
        except Exception:
            with self._lock:
                failed = self._calls.pop(call_id, None)
            if failed is not None:
                failed.close()
            logger.exception("Could not create call id=%s", call_id)
            raise
        logger.info("Created call id=%s destination=%s", call_id, destination)
        return session

    def get_call(self, call_id: UUID) -> CallSession | None:
        with self._lock:
            return self._calls.get(call_id)

    def active_calls(self) -> tuple[CallSession, ...]:
        with self._lock:
            return tuple(call for call in self._calls.values() if not call.is_terminal)

    def _on_call_state(self, event: SipEvent) -> None:
        if event.call_id is None or event.state is None or event.state.value not in {"disconnected", "failed"}:
            return
        # Do not close the session here: its own event handler still needs to
        # store the terminal snapshot for callers holding a session reference.
        with self._lock:
            self._calls.pop(event.call_id, None)

    def hangup_all(self) -> None:
        for session in self.active_calls():
            try:
                session.hangup()
            except SipCallError:
                logger.exception("Failed to hang up call id=%s", session.id)

    def remove_call(self, call_id: UUID) -> None:
        with self._lock:
            session = self._calls.pop(call_id, None)
        if session is not None:
            session.close()

    def close(self) -> None:
        self.hangup_all()
        with self._lock:
            call_ids = tuple(self._calls)
        for call_id in call_ids:
            self.remove_call(call_id)
        self._dispatcher.unsubscribe(EventType.CALL_STATE, self._on_call_state)
