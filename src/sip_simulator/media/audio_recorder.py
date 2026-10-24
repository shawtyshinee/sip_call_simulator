import logging
from pathlib import Path
from typing import Callable, Protocol

from ..exceptions import SipConfigurationError, SipMediaError, SipStateError

__all__ = [
    "RecorderPort",
    "SourceMedia",
    "AudioRecorder",

]


logger = logging.getLogger(__name__)


class RecorderPort(Protocol):
    def createRecorder(self, filename: str, enc_type: int = 0, max_size: int = 0, options: int = 0) -> None: ...


class SourceMedia(Protocol):
    def startTransmit(self, destination: object) -> None: ...
    def stopTransmit(self, destination: object) -> None: ...


class AudioRecorder:
    def __init__(self, factory: Callable[[], RecorderPort]) -> None:
        self._factory = factory
        self._recorder: RecorderPort | None = None
        self._source: SourceMedia | None = None
        self._path: Path | None = None

    @property
    def is_recording(self) -> bool:
        return self._recorder is not None

    def start(self, source_media: SourceMedia, destination: str | Path, *, overwrite: bool = False) -> Path:
        if self.is_recording:
            raise SipStateError("Recording already active")
        path = Path(destination).expanduser().resolve()
        if path.suffix.lower() != ".wav":
            raise SipConfigurationError("Recording destination must be .wav")
        if path.exists() and not overwrite:
            raise SipConfigurationError(f"Recording destination already exists: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        recorder = self._factory()
        try:
            recorder.createRecorder(str(path))
            source_media.startTransmit(recorder)
        except Exception as exc:
            logger.exception("Failed to start recording destination=%s", path)
            raise SipMediaError(f"Failed to start recording: {path}") from exc
        self._source, self._recorder, self._path = source_media, recorder, path
        logger.info("Recording started destination=%s", path)
        return path

    def stop(self) -> Path | None:
        source, recorder, path = self._source, self._recorder, self._path
        if recorder is None:
            return None
        try:
            if source is not None:
                source.stopTransmit(recorder)
        except Exception as exc:
            raise SipMediaError("Failed to stop recording") from exc
        finally:
            self._source = None
            self._recorder = None
            self._path = None
            logger.info("Recording stopped destination=%s", path)
        return path

    def close(self) -> None:
        self.stop()
