"""Exceptions exposed by :mod:`sip_simulator`."""

__all__ = ["SipError", "SipConfigurationError", "SipStateError", "SipBackendError", "SipRegistrationError", "SipCallError", "SipTimeoutError", "SipMediaError"]


class SipError(Exception):
    """Base class for all SDK-specific errors."""


class SipConfigurationError(SipError):
    """The supplied SIP or media configuration is invalid."""


class SipStateError(SipError):
    """An operation is invalid in the object's current lifecycle state."""


class SipBackendError(SipError):
    """The selected SIP backend failed to perform an operation."""


class SipRegistrationError(SipError):
    """SIP account registration or unregistration failed."""


class SipCallError(SipError):
    """Creating or controlling a SIP call failed."""


class SipTimeoutError(SipError):
    """A call did not reach the requested state before the deadline."""


class SipMediaError(SipError):
    """Audio validation, playback, recording, or media attachment failed."""
