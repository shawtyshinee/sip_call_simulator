from uuid import uuid4

import allure

from src.sip_simulator.core.events import CallEventState, EventDispatcher, EventType, SipEvent


@allure.epic("SIP simulator")
@allure.feature("Events")
class TestEventDispatcher:
    @allure.story("Dispatch call state")
    @allure.title("A subscribed handler receives only its event type")
    def test_dispatches_event_to_subscriber(self) -> None:
        dispatcher = EventDispatcher()
        received: list[SipEvent] = []
        dispatcher.subscribe(EventType.CALL_STATE, received.append)

        event = SipEvent(event_type=EventType.CALL_STATE, call_id=uuid4(), state=CallEventState.CALLING)
        dispatcher.publish(event)

        assert received == [event]

    @allure.story("Unsubscribe")
    @allure.title("An unsubscribed handler no longer receives events")
    def test_unsubscribe_removes_handler(self) -> None:
        dispatcher = EventDispatcher()
        received: list[SipEvent] = []
        dispatcher.subscribe(EventType.CALL_STATE, received.append)
        dispatcher.unsubscribe(EventType.CALL_STATE, received.append)

        dispatcher.publish(SipEvent(event_type=EventType.CALL_STATE, call_id=uuid4(), state=CallEventState.RINGING))

        assert received == []
