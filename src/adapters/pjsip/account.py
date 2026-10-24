"""PJSUA2 SIP account adapter."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any, Callable
from uuid import uuid4

from src.sip_simulator.config import SipConfig
from src.sip_simulator.core.events import EventType, SipEvent
from src.sip_simulator.exceptions import SipBackendError, SipCallError, SipRegistrationError, SipStateError

from .call import PjsipCall

logger = logging.getLogger(__name__)

try:
    import pjsua2 as pj
except ImportError:  # pragma: no cover - optional native dependency
    pj = SimpleNamespace()  # type: ignore[assignment]

_AccountBase = getattr(pj, "Account", object)
EventSink = Callable[[SipEvent], None]

__all__ = ["PjsipAccount"]


class PjsipAccount(_AccountBase):
    """Create/register an account and keep calls alive for PJSUA2 callbacks."""

    def __init__(self, config: SipConfig, event_sink: EventSink) -> None:
        if not hasattr(pj, "Account"):
            raise SipBackendError("PJSUA2 is required for the PJSIP backend")
        pj.Account.__init__(self)
        self._config = config
        self._event_sink = event_sink
        self._calls: dict[str, PjsipCall] = {}
        self._started = False
        self._closed = False

    @property
    def is_started(self) -> bool:
        return self._started

    def start(self) -> None:
        if self._closed:
            raise SipStateError("Account is closed")
        if self._started:
            return
        account_config = pj.AccountConfig()
        account_config.idUri = self._config.account_uri
        account_config.regConfig.registrarUri = self._config.registrar_uri
        account_config.regConfig.registerOnAdd = self._config.register_account
        password = self._config.password.get_secret_value()
        credential = pj.AuthCredInfo("digest", "*", self._config.username, 0, password)
        account_config.sipConfig.authCreds.append(credential)
        try:
            pj.Account.create(self, account_config)
        except Exception as exc:
            raise SipRegistrationError("Failed to create SIP account") from exc
        self._started = True
        logger.info("SIP account created uri=%s", self._config.account_uri)

    def register(self) -> None:
        self._require_started()
        try:
            pj.Account.setRegistration(self, True)
        except Exception as exc:
            raise SipRegistrationError("Failed to register SIP account") from exc

    def unregister(self) -> None:
        if self._started:
            try:
                pj.Account.setRegistration(self, False)
            except Exception as exc:
                raise SipRegistrationError("Failed to unregister SIP account") from exc

    def create_call(self, call_info_id: str) -> PjsipCall:
        self._require_started()
        key = str(call_info_id)
        if key in self._calls:
            raise SipCallError(f"Call already exists: {key}")
        call = PjsipCall(self, key, self._event_sink, on_terminal=self._release_call)
        self._calls[key] = call
        return call

    def onRegState(self, prm: Any) -> None:  # noqa: N802 - PJSUA2 callback name
        try:
            info = pj.Account.getInfo(self)
            code = int(getattr(info, "regStatus", 0) or 0)
            reason = str(getattr(info, "regStatusText", "")) or None
            registered = code // 100 == 2
            logger.info("SIP registration changed code=%s reason=%s", code, reason)
            self._event_sink(SipEvent(
                event_type=EventType.REGISTRATION,
                status_code=code if code >= 100 else None,
                reason=reason,
                details={"registered": registered, "registration_status": code},
            ))
        except Exception:
            logger.exception("Failed to process PJSIP registration callback")

    def onIncomingCall(self, prm: Any) -> None:  # noqa: N802 - PJSUA2 callback name
        native_call_id = getattr(prm, "callId", None)
        call_info_id = str(uuid4())
        try:
            call = PjsipCall(self, call_info_id, self._event_sink, native_call_id, on_terminal=self._release_call)
            self._calls[call_info_id] = call
            info = call.get_info()
            # The callback may arrive before all state callbacks; announce the
            # incoming dialog immediately so the core can create a session.
            call._publish(EventType.CALL_STATE, info.state, info.sip_status_code, info.sip_reason, incoming=True)
            logger.info("Incoming SIP call id=%s remote=%s", call_info_id, info.remote_uri)
        except Exception:
            logger.exception("Failed to create incoming PJSIP call")

    def close(self) -> None:
        if self._closed:
            return
        for call in tuple(self._calls.values()):
            try:
                call.close()
            except Exception:
                logger.debug("Failed to close PJSIP call", exc_info=True)
        self._calls.clear()
        if self._started:
            try:
                self.unregister()
            finally:
                try:
                    pj.Account.shutdown(self)
                except Exception as exc:
                    raise SipBackendError("Failed to close SIP account") from exc
                finally:
                    self._started = False
        self._closed = True

    def _release_call(self, call_info_id: str) -> None:
        call = self._calls.pop(call_info_id, None)
        if call is not None:
            call.close()

    def _require_started(self) -> None:
        if not self._started:
            raise SipStateError("PJSIP account is not started")
