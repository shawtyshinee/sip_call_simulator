import logging
from pathlib import Path
from typing import Callable, Protocol
from .audio_converter import validate_wav
from ..exceptions import SipMediaError, SipStateError

__all__ = [
    "MediaPort",
    "PlayerPort",
    "AudioPlayer"
]

logger = logging.getLogger(__name__)


class MediaPort(Protocol):
    def startTransmit(self, destination: object) -> None: ...
    def stopTransmit(self, destination: object) -> None: ...


class PlayerPort(MediaPort, Protocol):
    def createPlayer(self, filename: str, options: int = 0) -> None: ...


class AudioPlayer:
    """Keep native player alive while transmitting; createPlayer is WAV-only."""
    def __init__(self, factory: Callable[[], PlayerPort]) -> None:
        self._factory = factory
        self._player: PlayerPort | None = None
        self._target: object | None = None

    @property
    def is_playing(self) -> bool:
        return self._target is not None

    def play(self, wav_path: str | Path, target_media: object, *, loop: bool = False) -> None:
        if self._player is not None:
            raise SipStateError("Player already in use; stop it before replaying")
        path = validate_wav(wav_path)
        player = self._factory()
        # PJSUA2 option 1 is PJMEDIA_FILE_NO_LOOP; use 0 to loop.
        options = 0 if loop else 1
        try:
            player.createPlayer(str(path), options)
            player.startTransmit(target_media)
        except Exception as exc:
            logger.exception("Failed to play WAV path=%s", path)
            raise SipMediaError(f"Failed to play WAV: {path}") from exc
        self._player, self._target = player, target_media
        logger.info("Audio playback started path=%s loop=%s", path, loop)

    def stop(self) -> None:
        player, target = self._player, self._target
        if player is None:
            return
        try:
            if target is not None:
                player.stopTransmit(target)
        except Exception as exc:
            raise SipMediaError("Failed to stop audio playback") from exc
        finally:
            self._target = None
            self._player = None
            logger.info("Audio playback stopped")

    def close(self) -> None:
        self.stop()
