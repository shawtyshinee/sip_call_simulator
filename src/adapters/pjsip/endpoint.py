"""PJSUA2 endpoint adapter."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

from src.sip_simulator.config import SipConfig, SipTransport
from src.sip_simulator.exceptions import SipBackendError, SipConfigurationError, SipStateError

logger = logging.getLogger(__name__)

try:  # PJSUA2 is an optional native dependency during unit testing.
    import pjsua2 as pj
except ImportError:  # pragma: no cover - exercised only without PJSUA2
    pj = SimpleNamespace()  # type: ignore[assignment]

__all__ = ["PjsipEndpoint"]


def _require_pjsua2() -> None:
    if not hasattr(pj, "Endpoint"):
        raise SipBackendError(
            "PJSUA2 is required for the PJSIP backend; install the 'pjsua2' "
            "Python bindings before starting an endpoint"
        )


class PjsipEndpoint:
    """Own a ``pj.Endpoint`` and run it in explicitly polled mode."""

    def __init__(self, config: SipConfig) -> None:
        self._config = config
        self._endpoint: Any | None = None
        self._transport_id: Any | None = None
        self._is_running = False

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def native_endpoint(self) -> Any:
        if self._endpoint is None:
            raise SipStateError("PJSIP endpoint has not been started")
        return self._endpoint

    def start(self) -> None:
        if self._is_running:
            return
        _require_pjsua2()
        logger.info("PJSIP endpoint initialization started")
        endpoint = pj.Endpoint()
        try:
            endpoint.libCreate()
            ep_config = pj.EpConfig()
            ep_config.uaConfig.threadCnt = 0
            ep_config.uaConfig.mainThreadOnly = True
            # PJSUA2 uses its own log-level scale.  Keep the SDK configuration
            # bounded rather than assuming Python logging constants match it.
            if hasattr(ep_config, "logConfig"):
                ep_config.logConfig.level = min(6, max(0, self._config.log_level // 10))
                ep_config.logConfig.consoleLevel = min(6, max(0, self._config.log_level // 10))
            endpoint.libInit(ep_config)

            transport_config = pj.TransportConfig()
            transport_config.port = self._config.local_port
            transport = self._config.transport
            transport_type = {
                SipTransport.UDP: pj.PJSIP_TRANSPORT_UDP,
                SipTransport.TCP: pj.PJSIP_TRANSPORT_TCP,
                SipTransport.TLS: pj.PJSIP_TRANSPORT_TLS,
            }[SipTransport(transport)]
            self._transport_id = endpoint.transportCreate(transport_type, transport_config)
            logger.info("SIP transport created protocol=%s port=%s", transport.value, self._config.local_port)
            endpoint.libStart()
        except Exception as exc:
            logger.exception("Failed to initialize PJSIP endpoint")
            # libDestroy is safe after a partially completed libCreate; do not
            # retain a half-created native object for a later start attempt.
            try:
                endpoint.libDestroy()
            except Exception:
                logger.debug("PJSIP cleanup after failed startup failed", exc_info=True)
            self._endpoint = None
            self._transport_id = None
            raise SipBackendError("Failed to initialize PJSIP endpoint") from exc
        self._endpoint = endpoint
        self._is_running = True
        logger.info("PJSIP endpoint started")

    def poll(self, timeout_ms: int = 50) -> int:
        if not self._is_running or self._endpoint is None:
            raise SipStateError("PJSIP endpoint is not running")
        if timeout_ms < 0:
            raise SipConfigurationError("timeout_ms must be nonnegative")
        try:
            processed = self._endpoint.libHandleEvents(timeout_ms)
        except Exception as exc:
            raise SipBackendError("Failed to process PJSIP events") from exc
        if processed:
            logger.debug("PJSIP events processed count=%s", processed)
        return int(processed)

    def stop(self) -> None:
        if self._endpoint is None:
            self._is_running = False
            return
        endpoint, self._endpoint = self._endpoint, None
        self._is_running = False
        self._transport_id = None
        try:
            endpoint.libDestroy()
        except Exception as exc:
            raise SipBackendError("Failed to stop PJSIP endpoint") from exc
        finally:
            logger.info("PJSIP endpoint stopped")
