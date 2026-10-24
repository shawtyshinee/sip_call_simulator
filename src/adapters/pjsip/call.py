"""PJSUA2 implementation of a single SIP dialog."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any, Callable
from uuid import UUID

from src.sip_simulator.core.events import CallEventState, EventType, SipEvent
from src.sip_simulator.models.call_info import CallInfo
from src.sip_simulator.models.call_state import CallState
from src.sip_simulator.exceptions import SipBackendError, SipCallError, SipMediaError, SipStateError

logger = logging.getLogger(__name__)

try:  # Keep importing the SDK possible on hosts used for non-SIP tests.
    import pjsua2 as pj
except ImportError:  # pragma: no cover - depends on optional native package
    pj = SimpleNamespace()  # type: ignore[assignment]

_CallBase = getattr(pj, "Call", object)
EventSink = Callable[[SipEvent], None]

__all__ = ["PjsipCall", "map_call_state"]


def _constant(name: str) -> Any:
    return getattr(pj, name, object())


def map_call_state(native_state: Any, *, status_code: int | None = None) -> CallState:
    """Convert a PJSIP invite state without leaking PJSIP constants outward."""
    mapping = {
        _constant("PJSIP_INV_STATE_NULL"): CallState.IDLE,
        _constant("PJSIP_INV_STATE_CALLING"): CallState.CALLING,
        _constant("PJSIP_INV_STATE_INCOMING"): CallState.RINGING,
        _constant("PJSIP_INV_STATE_EARLY"): CallState.RINGING,
        _constant("PJSIP_INV_STATE_CONNECTING"): CallState.CALLING,
        _constant("PJSIP_INV_STATE_CONFIRMED"): CallState.CONNECTED,
    }
    if native_state == _constant("PJSIP_INV_STATE_DISCONNECTED"):
        # A final non-2xx status is a failed attempt (Busy, Decline, timeout),
        # whereas BYE after a confirmed call is an ordinary disconnection.
        return CallState.FAILED if status_code is not None and status_code >= 300 else CallState.DISCONNECTED
    return mapping.get(native_state, CallState.IDLE)


def _event_state(state: CallState) -> CallEventState:
    return CallEventState(state.value)


class PjsipCall(_CallBase):
    """Native ``pj.Call`` wrapper with SDK identifiers and event conversion."""

    def __init__(
        self,
        account: Any,
        call_info_id: str,
        event_sink: EventSink,
        call_id: int | None = None,
        *,
        on_terminal: Callable[[str], None] | None = None,
    ) -> None:
        if not hasattr(pj, "Call"):
            raise SipBackendError("PJSUA2 is required for the PJSIP backend")
        native_call_id = getattr(pj, "PJSUA_INVALID_ID", -1) if call_id is None else call_id
        pj.Call.__init__(self, account, native_call_id)
        self._call_info_id = str(call_info_id)
        self._event_sink = event_sink
        self._on_terminal = on_terminal
        self._closed = False
        self._audio_media: Any | None = None
        self._last_info: CallInfo | None = None

    @property
    def call_info_id(self) -> str:
        return self._call_info_id

    def make_call(self, destination_uri: str) -> None:
        if self._closed:
            raise SipStateError("Call is closed")
        if not destination_uri.strip():
            raise SipCallError("destination_uri must not be empty")
        prm = pj.CallOpParam(True)
        try:
            pj.Call.makeCall(self, destination_uri, prm)
        except Exception as exc:
            raise SipCallError(f"Unable to make call to {destination_uri}") from exc

    def answer(self, status_code: int = 200) -> None:
        if not 100 <= status_code <= 699:
            raise SipCallError("status_code must be between 100 and 699")
        prm = pj.CallOpParam()
        prm.statusCode = status_code
        try:
            pj.Call.answer(self, prm)
        except Exception as exc:
            raise SipCallError("Unable to answer call") from exc

    def hangup(self, status_code: int = 0) -> None:
        if status_code and not 100 <= status_code <= 699:
            raise SipCallError("status_code must be 0 or between 100 and 699")
        if self._closed:
            return
        prm = pj.CallOpParam()
        prm.statusCode = status_code
        # Calling through the base type avoids recursion into this method.
        try:
            pj.Call.hangup(self, prm)
        except Exception as exc:
            raise SipCallError("Unable to hang up call") from exc

    terminate = hangup

    def send_dtmf(self, digits: str) -> None:
        if not digits:
            raise SipCallError("digits must not be empty")
        try:
            pj.Call.dialDtmf(self, digits)
        except Exception as exc:
            raise SipCallError("Unable to send DTMF") from exc

    def get_info(self) -> CallInfo:
        try:
            native = pj.Call.getInfo(self)
        except Exception as exc:
            raise SipCallError("Unable to retrieve call information") from exc
        status_code = getattr(native, "lastStatusCode", None)
        status_code = int(status_code) if status_code and int(status_code) >= 100 else None
        info = CallInfo(
            call_info_id=self._call_info_id,
            remote_uri=str(getattr(native, "remoteUri", "")),
            state=map_call_state(getattr(native, "state", None), status_code=status_code),
            sip_status_code=status_code,
            sip_reason=str(getattr(native, "lastReason", "")) or None,
        )
        self._last_info = info
        return info

    def get_audio_media(self) -> Any:
        if self._audio_media is not None:
            return self._audio_media
        try:
            info = pj.Call.getInfo(self)
        except Exception as exc:
            raise SipMediaError("Unable to retrieve call media") from exc
        for index, media in enumerate(getattr(info, "media", ())):
            if getattr(media, "type", None) != getattr(pj, "PJMEDIA_TYPE_AUDIO", None):
                continue
            if getattr(media, "status", None) not in {
                getattr(pj, "PJSUA_CALL_MEDIA_ACTIVE", None),
                getattr(pj, "PJSUA_CALL_MEDIA_REMOTE_HOLD", None),
            }:
                continue
            try:
                self._audio_media = pj.Call.getAudioMedia(self, index)
            except Exception as exc:
                raise SipMediaError("Unable to retrieve call audio media") from exc
            return self._audio_media
        raise SipMediaError("No active audio media is available for this call")

    def onCallState(self, prm: Any) -> None:  # noqa: N802 - PJSUA2 callback name
        try:
            info = self.get_info()
            self._publish(EventType.CALL_STATE, info.state, info.sip_status_code, info.sip_reason)
            logger.info(
                "SIP call state changed id=%s state=%s status=%s",
                self._call_info_id, info.state.value, info.sip_status_code,
            )
            if info.state in {CallState.DISCONNECTED, CallState.FAILED}:
                self._audio_media = None
                if self._on_terminal is not None:
                    self._on_terminal(self._call_info_id)
        except Exception:
            logger.exception("Failed to process PJSIP call-state callback id=%s", self._call_info_id)

    def onCallMediaState(self, prm: Any) -> None:  # noqa: N802 - PJSUA2 callback name
        try:
            info = self.get_info()
            try:
                self.get_audio_media()
                ready = True
            except SipMediaError:
                ready = False
            self._publish(EventType.MEDIA_STATE, info.state, info.sip_status_code, info.sip_reason, media_ready=ready)
        except Exception:
            logger.exception("Failed to process PJSIP media-state callback id=%s", self._call_info_id)

    def close(self) -> None:
        """Release Python references only after PJSIP reported termination."""
        self._audio_media = None
        self._closed = True

    def _publish(
        self,
        event_type: EventType,
        state: CallState,
        status_code: int | None,
        reason: str | None,
        **details: Any,
    ) -> None:
        try:
            call_id: UUID | None = UUID(self._call_info_id)
        except ValueError:
            # The public adapter contract permits arbitrary strings.  Preserve
            # it in details when used outside the UUID-based current core.
            call_id = None
            details["call_info_id"] = self._call_info_id
        self._event_sink(SipEvent(
            event_type=event_type,
            call_id=call_id,
            state=_event_state(state),
            status_code=status_code,
            reason=reason,
            details=details,
        ))
