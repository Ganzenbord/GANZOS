"""Een geüpload audiofragment inlezen en nakijken.

Alleen WAV, en met de `wave`-module uit Python zelf: dat scheelt een extra pakket dat op Mac
en Windows apart geïnstalleerd moet worden. Wie iets anders aanlevert krijgt een melding met
de ffmpeg-regel die het omzet.
"""

from __future__ import annotations

import io
import wave
from dataclasses import dataclass

import numpy as np

# De kloktikken per seconde waarop het herkenmodel getraind is.
TARGET_SAMPLE_RATE = 16_000

_SUPPORTED_WIDTHS = {1: np.uint8, 2: np.int16, 4: np.int32}


class AudioError(ValueError):
    """Het fragment is niet te gebruiken. De tekst is bedoeld voor de gebruiker."""


@dataclass(frozen=True, slots=True)
class AudioClip:
    samples: np.ndarray
    sample_rate: int

    @property
    def seconds(self) -> float:
        return len(self.samples) / self.sample_rate if self.sample_rate else 0.0


def load_wav(data: bytes, *, min_seconds: float, max_seconds: float) -> AudioClip:
    """Lees WAV-bytes in als één spoor van -1.0 tot 1.0."""
    if not data:
        raise AudioError("Er kwam een leeg bestand binnen.")

    try:
        with wave.open(io.BytesIO(data), "rb") as bestand:
            kanalen = bestand.getnchannels()
            breedte = bestand.getsampwidth()
            tempo = bestand.getframerate()
            frames = bestand.readframes(bestand.getnframes())
    except wave.Error as exc:
        raise AudioError(
            "Dit is geen leesbaar WAV-bestand. Omzetten kan met: "
            "ffmpeg -i opname.m4a -ac 1 -ar 16000 opname.wav"
        ) from exc

    if breedte not in _SUPPORTED_WIDTHS:
        raise AudioError(
            f"WAV met {breedte * 8} bits per meting wordt niet ondersteund. Omzetten kan met: "
            "ffmpeg -i opname.wav -ac 1 -ar 16000 -sample_fmt s16 opname-16.wav"
        )
    if tempo <= 0:
        raise AudioError("Het bestand vermeldt geen geldige bemonsteringsfrequentie.")

    metingen = np.frombuffer(frames, dtype=_SUPPORTED_WIDTHS[breedte])
    if metingen.size == 0:
        raise AudioError("Het fragment bevat geen geluid.")

    if breedte == 1:
        # 8-bits WAV telt vanaf 0 in plaats van rond nul.
        genormaliseerd = (metingen.astype(np.float32) - 128.0) / 128.0
    else:
        maximum = float(np.iinfo(_SUPPORTED_WIDTHS[breedte]).max)
        genormaliseerd = metingen.astype(np.float32) / maximum

    if kanalen > 1:
        bruikbaar = (genormaliseerd.size // kanalen) * kanalen
        genormaliseerd = genormaliseerd[:bruikbaar].reshape(-1, kanalen).mean(axis=1)

    clip = AudioClip(samples=genormaliseerd.astype(np.float32), sample_rate=tempo)

    if clip.seconds < min_seconds:
        raise AudioError(
            f"Het fragment duurt {clip.seconds:.1f} seconde. "
            f"Neem er minstens {min_seconds:.0f} op, anders valt er weinig te herkennen."
        )
    if clip.seconds > max_seconds:
        raise AudioError(
            f"Het fragment duurt {clip.seconds:.1f} seconden; {max_seconds:.0f} is het maximum."
        )
    return clip
