"""Compatibility package for source-tree imports.

Applications should import the public SDK from :mod:`src.sip_simulator`.
"""

from .sip_simulator import (
    CallInfo,
    CallState,
    RegistrationState,
    SipAccount,
    SipBackendError,
    SipCallError,
    SipClient,
    SipConfig,
    SipConfigurationError,
    SipError,
    SipMediaError,
    SipRegistrationError,
    SipStateError,
    SipTimeoutError,
    SipTransport,
)

__all__ = [
    "CallInfo", "CallState", "RegistrationState", "SipAccount", "SipBackendError", "SipCallError",
    "SipClient", "SipConfig", "SipConfigurationError", "SipError", "SipMediaError",
    "SipRegistrationError", "SipStateError", "SipTimeoutError", "SipTransport",
]
