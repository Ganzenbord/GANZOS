"""Stemherkenning: het koppelvlak en de SpeechBrain-implementatie."""

from app.integrations.voice.encoder import (
    DEFAULT_MODEL,
    SpeakerEncoder,
    SpeakerEncoderUnavailableError,
    SpeechBrainEncoder,
)

__all__ = [
    "DEFAULT_MODEL",
    "SpeakerEncoder",
    "SpeakerEncoderUnavailableError",
    "SpeechBrainEncoder",
]
