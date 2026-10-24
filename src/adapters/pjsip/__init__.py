"""PJSUA2-backed implementations of the adapter contracts."""

from __future__ import annotations

from collections.abc import Callable

from src.adapters.base import AccountBackend, EndpointBackend
from src.sip_simulator.config import SipConfig
from src.sip_simulator.core.events import SipEvent
from src.sip_simulator.exceptions import SipConfigurationError, SipStateError

from .account import PjsipAccount
from .call import PjsipCall, map_call_state
from .endpoint import PjsipEndpoint

__all__ = [
    "PjsipAccount",
    "PjsipBackendFactory",
    "PjsipCall",
    "PjsipEndpoint",
    "map_call_state",
]


class PjsipBackendFactory:
    """Wire PJSIP adapters together while keeping the core PJSIP-free."""

    def __init__(self, event_sink: Callable[[SipEvent], None]) -> None:
        self._event_sink = event_sink

    def create_endpoint(self, config: SipConfig) -> EndpointBackend:
        return PjsipEndpoint(config)

    def create_account(
        self, endpoint: EndpointBackend, config: SipConfig
    ) -> AccountBackend:
        if not isinstance(endpoint, PjsipEndpoint):
            raise SipConfigurationError("PjsipBackendFactory requires a PjsipEndpoint")
        if not endpoint.is_running:
            raise SipStateError("Start the PJSIP endpoint before creating an account")
        return PjsipAccount(config, self._event_sink)
