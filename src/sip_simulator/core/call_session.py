"""The SDK-level representation of one SIP call."""

from __future__ import annotations

import logging
from time import monotonic
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from ..exceptions import SipCallError, SipConfigurationError, SipMediaError, SipStateError, SipTimeoutError
from .engine import SipEngine
from .events import CallEventState, EventDispatcher, EventType, SipEvent

__all__ = ["CallBackend", "CallSession", "CallSnapshot", "TERMINAL_STATES"]
logger = logging.getLogger(__name__)
TERMINAL_STATES = frozenset({CallEventState.DISCONNECTED, CallEventState.FAILED})


class CallSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)
    snapshot_id: UUID
    destination: str
    state: CallEventState
    status_code: int | None = None
    reason: str | None = None


class CallBackend(Protocol):
    def make_call(self, destination: str) -> None: ...
    def answer(self, status_code: int = 200) -> None: ...
    def hangup(self, status_code: int = 0) -> None: ...
    def send_dtmf(self, digits: str) -> None: ...
    def get_audio_media(self) -> object: ...
    def close(self) -> None: ...


class CallSession:
    def __init__(self, call_id: UUID, destination: str, backend: CallBackend, engine: SipEngine, dispatcher: EventDispatcher) -> None:
        self.call_session_id = call_id
        self.destination = destination
        self._backend = backend
        self._engine = engine
        self._dispatcher = dispatcher
        self._snapshot = CallSnapshot(snapshot_id=call_id, destination=destination, state=CallEventState.NEW)
        self._history: list[SipEvent] = []
        self._closed = False
        dispatcher.subscribe(EventType.CALL_STATE, self._on_event)

    @property
    def id(self) -> UUID:
        return self.call_session_id

    @property
    def info(self) -> CallSnapshot:
        return self._snapshot

    @property
    def history(self) -> tuple[SipEvent, ...]:
        return tuple(self._history)

    @property
    def is_terminal(self) -> bool:
        return self._snapshot.state in TERMINAL_STATES

    def _on_event(self, event: SipEvent) -> None:
        if event.call_id != self.call_session_id or event.state is None:
            return
        self._snapshot = self._snapshot.model_copy(update={"state": event.state, "status_code": event.status_code, "reason": event.reason})
        self._history.append(event)
        logger.info("Call %s state=%s status=%s", self.call_session_id, event.state, event.status_code)

    def start(self) -> None:
        if self._snapshot.state is not CallEventState.NEW:
            raise SipStateError("Call has already been started")
        try:
            self._backend.make_call(self.destination)
        except Exception as exc:
            raise SipCallError(f"Unable to start call to {self.destination}") from exc

    def answer(self, status_code: int = 200) -> None:
        try:
            self._backend.answer(status_code)
        except Exception as exc:
            raise SipCallError("Unable to answer call") from exc

    def send_dtmf(self, digits: str) -> None:
        try:
            self._backend.send_dtmf(digits)
        except Exception as exc:
            raise SipCallError("Unable to send DTMF") from exc

    def get_audio_media(self) -> object:
        try:
            return self._backend.get_audio_media()
        except Exception as exc:
            raise SipMediaError("No active audio media is available") from exc

    def wait_for_state(self, expected: CallEventState, timeout: float = 15.0) -> CallSnapshot:
        if timeout < 0:
            raise SipConfigurationError("timeout must be nonnegative")
        deadline = monotonic() + timeout
        while True:
            current = self._snapshot.state
            if current is expected:
                return self._snapshot
            if current in TERMINAL_STATES:
                raise SipCallError(f"Call {self.id} terminated in state {current.value}")
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise SipTimeoutError(f"Call {self.id} did not reach {expected.value} within {timeout}s")
            self._engine.poll(min(self._engine.config.event_poll_ms, max(1, int(remaining * 1000))))

    def wait_for_answer(self, timeout: float = 15.0) -> CallSnapshot:
        return self.wait_for_state(CallEventState.CONNECTED, timeout)

    def hangup(self, status_code: int = 0) -> None:
        if self.is_terminal:
            return
        try:
            self._backend.hangup(status_code)
        except Exception as exc:
            raise SipCallError("Unable to hang up call") from exc

    def close(self) -> None:
        if self._closed:
            return
        self._dispatcher.unsubscribe(EventType.CALL_STATE, self._on_event)
        try:
            self._backend.close()
        except Exception:
            logger.exception("Failed to close call backend id=%s", self.id)
        self._closed = True
