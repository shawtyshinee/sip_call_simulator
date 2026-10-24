import logging
import subprocess
import wave
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field

from ..exceptions import SipConfigurationError, SipMediaError

__all__ = [
    "AudioFormat",
    "AudioConversionError",
    "validate_wav",
    "convert_to_wav"
]

logger = logging.getLogger(__name__)

class AudioFormat(BaseModel):
    model_config = ConfigDict(frozen=True)
    sample_rate: int = Field(default=8000, gt=0)
    channels: int = Field(default=1, ge=1, le=2)
    sample_width: int = Field(default=2, ge=1, le=4)

class AudioConversionError(SipMediaError):
    """Audio conversion or WAV validation failed."""

def validate_wav(path: str | Path, expected: AudioFormat | None = None) -> Path:
    try:
        source = Path(path).expanduser().resolve(strict=True)
        with wave.open(str(source), "rb") as wav:
            actual = AudioFormat(sample_rate=wav.getframerate(), channels=wav.getnchannels(), sample_width=wav.getsampwidth())
            if wav.getcomptype() != "NONE":
                raise AudioConversionError("WAV must be uncompressed PCM")
    except (FileNotFoundError, OSError, wave.Error, EOFError) as exc:
        raise AudioConversionError(f"Invalid WAV: {path}") from exc
    if expected is not None and actual != expected:
        raise AudioConversionError(f"WAV format {actual} does not match required {expected}")
    logger.debug("Validated WAV path=%s format=%s", source, actual)
    return source

def convert_to_wav(source: str | Path, destination: str | Path, *, audio_format: AudioFormat | None = None, overwrite: bool = False) -> Path:
    fmt = audio_format or AudioFormat()
    try:
        src = Path(source).expanduser().resolve(strict=True)
    except FileNotFoundError as exc:
        raise AudioConversionError(f"Audio source does not exist: {source}") from exc
    dst = Path(destination).expanduser().resolve()
    if src == dst:
        raise SipConfigurationError("Source and destination must be different")
    if dst.exists() and not overwrite:
        raise SipConfigurationError(f"Audio destination already exists: {dst}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    if fmt.sample_width != 2:
        raise SipConfigurationError("FFmpeg converter currently supports 16-bit PCM only")
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y" if overwrite else "-n", "-i", str(src), "-ac", str(fmt.channels), "-ar", str(fmt.sample_rate), "-c:a", "pcm_s16le", str(dst)]
    logger.info("Converting audio source=%s destination=%s", src, dst)
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=120)
        return validate_wav(dst, fmt)
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.exception("Audio conversion failed source=%s", src)
        raise AudioConversionError(f"Failed to convert audio: {src}") from exc
