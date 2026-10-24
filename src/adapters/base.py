"""Backend contracts used by the SIP core.

The contracts deliberately contain no PJSUA2 types.  This keeps the domain
layer testable with small fakes and makes it possible to provide another SIP
implementation in the future.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.sip_simulator.config import SipConfig
from src.sip_simulator.models.call_info import CallInfo

__all__ = [
    "CallBackend",
    "AccountBackend",
    "EndpointBackend",
    "SipBackendFactory",
]


@runtime_checkable
class CallBackend(Protocol):
    @property
    def call_info_id(self) -> str: ...

    def make_call(self, destination_uri: str) -> None: ...

    def answer(self, status_code: int = 200) -> None: ...

    def hangup(self, status_code: int = 0) -> None: ...

    def send_dtmf(self, digits: str) -> None: ...

    def get_info(self) -> CallInfo: ...

    def close(self) -> None: ...


@runtime_checkable
class AccountBackend(Protocol):
    def start(self) -> None: ...

    def register(self) -> None: ...

    def unregister(self) -> None: ...

    def create_call(self, call_info_id: str) -> CallBackend: ...

    def close(self) -> None: ...


@runtime_checkable
class EndpointBackend(Protocol):
    def start(self) -> None: ...

    def poll(self, timeout_ms: int = 50) -> int: ...

    def stop(self) -> None: ...


@runtime_checkable
class SipBackendFactory(Protocol):
    def create_endpoint(self, config: SipConfig) -> EndpointBackend: ...

    def create_account(
        self, endpoint: EndpointBackend, config: SipConfig
    ) -> AccountBackend: ...
