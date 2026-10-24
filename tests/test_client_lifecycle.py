from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

import allure

from src.sip_simulator.client import SipClient
from src.sip_simulator.config import SipConfig
from src.sip_simulator.core.events import CallEventState, EventType, SipEvent


@dataclass
class FakeEndpoint:
    started: bool = False
    stopped: bool = False
    poll_calls: list[int] = field(default_factory=list)

    def start(self) -> None:
        self.started = True

    def poll(self, timeout_ms: int = 50) -> int:
        self.poll_calls.append(timeout_ms)
        return 0

    def stop(self) -> None:
        self.stopped = True


@dataclass
class FakeCall:
    destination: str | None = None
    hung_up: bool = False
    closed: bool = False

    def make_call(self, destination: str) -> None:
        self.destination = destination

    def answer(self, status_code: int = 200) -> None:
        return None

    def hangup(self, status_code: int = 0) -> None:
        self.hung_up = True

    def send_dtmf(self, digits: str) -> None:
        return None

    def get_audio_media(self) -> object:
        return object()

    def close(self) -> None:
        self.closed = True


@dataclass
class FakeAccount:
    started: bool = False
    closed: bool = False
    calls: dict[str, FakeCall] = field(default_factory=dict)

    def start(self) -> None:
        self.started = True

    def register(self) -> None:
        return None

    def unregister(self) -> None:
        return None

    def create_call(self, call_info_id: str) -> FakeCall:
        call = FakeCall()
        self.calls[call_info_id] = call
        return call

    def close(self) -> None:
        self.closed = True


class FakeBackendFactory:
    def __init__(self) -> None:
        self.endpoint = FakeEndpoint()
        self.account = FakeAccount()

    def create_endpoint(self, config: SipConfig) -> FakeEndpoint:
        return self.endpoint

    def create_account(self, endpoint: FakeEndpoint, config: SipConfig) -> FakeAccount:
        assert endpoint is self.endpoint
        assert endpoint.started
        return self.account


@allure.epic("SIP simulator")
@allure.feature("Client lifecycle")
class TestSipClient:
    @allure.story("Outgoing call")
    @allure.title("Client starts, creates a call, receives state event, and cleans up")
    def test_client_call_lifecycle_with_fake_backend(self) -> None:
        factory = FakeBackendFactory()
        config = SipConfig(host="pbx.example.test", username="1000", password="secret")
        client = SipClient(config, backend_factory=factory)

        client.start()
        session = client.call("1001")
        native_call = factory.account.calls[str(session.id)]
        assert native_call.destination == "sip:1001@pbx.example.test"

        client.dispatcher.publish(
            SipEvent(event_type=EventType.CALL_STATE, call_id=session.id, state=CallEventState.CONNECTED)
        )
        assert session.wait_for_answer(timeout=0).state is CallEventState.CONNECTED

        client.stop()
        assert native_call.hung_up
        assert native_call.closed
        assert factory.endpoint.stopped
        assert factory.account.closed
