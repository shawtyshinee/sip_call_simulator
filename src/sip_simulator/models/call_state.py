from enum import Enum

__all__ = [
    "CallState"
]


class CallState(str, Enum):
    IDLE = "idle"
    CALLING = "calling"
    RINGING = "ringing"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    FAILED = "failed"
