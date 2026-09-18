"""Gereedschap voor de stemtests: nepopnames en een namaak-herkenner.

Er wordt geen model geladen. Elke opname draagt een merkteken in de allereerste meting, en
de namaak-herkenner leest dat terug en geeft de afdruk die de test eraan gekoppeld heeft.
Zo is precies te sturen wie er "gesproken" heeft — zonder netwerk, zonder torch, zonder
wachten. Wat de tests controleren is dan ook niet of het model goed luistert (dat is aan
SpeechBrain), maar of de toegangsregels kloppen.
"""

from __future__ import annotations

import io
import struct
import wave

import numpy as np

from app.utils.audio import AudioClip
from app.utils.embeddings import l2_normalize

SAMPLE_RATE = 16_000
MARKER_STEP = 1000

# Merktekens die de tests gebruiken.
STEF = 1
BROER = 2
BUURVROUW = 3
VREEMDE = 7


def maak_wav(
    marker: int,
    *,
    seconds: float = 2.0,
    sample_rate: int = SAMPLE_RATE,
    channels: int = 1,
    variant: int = 0,
) -> bytes:
    """Een WAV-opname met een merkteken erin.

    `variant` verandert de rest van de golf: dezelfde spreker, een andere opname.
    """
    aantal = max(int(seconds * sample_rate), 1)
    rng = np.random.default_rng(seed=1000 * marker + variant)
    metingen = (rng.normal(0, 0.05, size=aantal) * 32767).astype(np.int16)
    metingen[0] = marker * MARKER_STEP

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as bestand:
        bestand.setnchannels(channels)
        bestand.setsampwidth(2)
        bestand.setframerate(sample_rate)
        if channels == 1:
            bestand.writeframes(metingen.tobytes())
        else:
            # Beide kanalen hetzelfde, zodat het gemiddelde het merkteken houdt.
            bestand.writeframes(np.repeat(metingen, channels).tobytes())
    return buffer.getvalue()


def maak_wav_met_breedte(sampwidth: int, *, seconds: float = 2.0) -> bytes:
    """Een WAV met een afwijkend aantal bits per meting, om de foutmelding te testen."""
    aantal = max(int(seconds * SAMPLE_RATE), 1)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as bestand:
        bestand.setnchannels(1)
        bestand.setsampwidth(sampwidth)
        bestand.setframerate(SAMPLE_RATE)
        bestand.writeframes(b"\x00" * (aantal * sampwidth))
    return buffer.getvalue()


def geen_wav() -> bytes:
    """Iets dat op een bestand lijkt maar geen WAV is."""
    return struct.pack("<4sI4s", b"RIFF", 4, b"NIET")


def lees_marker(clip: AudioClip) -> int:
    return int(round(float(clip.samples[0]) * 32767 / MARKER_STEP))


class FakeEncoder:
    """Doet alsof hij luistert.

    Elk merkteken hoort bij een vaste afdruk. Een merkteken dat niet is aangeleerd, levert
    de afdruk van "een vreemde" op: die lijkt op niemand.
    """

    def __init__(self, model_name: str = "test-encoder", dimension: int = 8) -> None:
        self._model_name = model_name
        self._dimension = dimension
        self._voices: dict[int, list[float]] = {}
        self.calls = 0

    @property
    def model_name(self) -> str:
        return self._model_name

    def teach(self, marker: int, embedding: list[float] | None = None) -> list[float]:
        if embedding is None:
            embedding = [0.0] * self._dimension
            embedding[marker % self._dimension] = 1.0
        afdruk = l2_normalize(embedding)
        self._voices[marker] = afdruk
        return afdruk

    async def embed(self, clip: AudioClip) -> list[float]:
        self.calls += 1
        marker = lees_marker(clip)
        if marker in self._voices:
            return self._voices[marker]
        vreemde = [0.0] * self._dimension
        vreemde[-1] = 1.0
        return vreemde


class KapotteEncoder:
    """Doet alsof SpeechBrain niet geïnstalleerd is."""

    model_name = "niet-beschikbaar"

    async def embed(self, clip: AudioClip) -> list[float]:
        from app.integrations.voice import SpeakerEncoderUnavailableError

        raise SpeakerEncoderUnavailableError(
            "Stemherkenning is niet geïnstalleerd. Installeer het eenmalig met: "
            "pip install -r requirements-voice.txt"
        )
