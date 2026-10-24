"""Thread-safe domain events emitted by SIP adapters."""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable, MutableMapping
from datetime import datetime, timezone
from enum import Enum
from threading import RLock
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["CallEventState", "EventDispatcher", "EventHandler", "EventType", "SipEvent"]
logger = logging.getLogger(__name__)


class CallEventState(str, Enum):
    NEW = "new"
    CALLING = "calling"
    RINGING = "ringing"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    FAILED = "failed"


class EventType(str, Enum):
    CALL_STATE = "call_state"
    MEDIA_STATE = "media_state"
    REGISTRATION = "registration"


class SipEvent(BaseModel):
    model_config = ConfigDict(frozen=True)
    event_type: EventType
    call_id: UUID | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    state: CallEventState | None = None
    status_code: int | None = Field(default=None, ge=100, le=699)
    reason: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


EventHandler = Callable[[SipEvent], None]


class EventDispatcher:
    def __init__(self) -> None:
        self._handlers: MutableMapping[EventType, list[EventHandler]] = defaultdict(list)
        self._lock = RLock()

    def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        with self._lock:
            if handler not in self._handlers[event_type]:
                self._handlers[event_type].append(handler)

    def unsubscribe(self, event_type: EventType, handler: EventHandler) -> None:
        with self._lock:
            handlers = self._handlers.get(event_type)
            if handlers and handler in handlers:
                handlers.remove(handler)

    def publish(self, event: SipEvent) -> None:
        logger.debug("Dispatch event type=%s call_id=%s", event.event_type, event.call_id)
        with self._lock:
            handlers = tuple(self._handlers.get(event.event_type, ()))
        for handler in handlers:
            try:
                handler(event)
            except Exception:
                logger.exception("Event handler failed: type=%s call_id=%s", event.event_type, event.call_id)
