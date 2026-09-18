"""Van een geluidsfragment naar een vingerafdruk van de stem.

Het rekenwerk doet SpeechBrain met het ECAPA-TDNN-model. Dat brengt torch mee (honderden
megabytes) en dat wil je niet opleggen aan wie alleen even de backend wil starten. Daarom
zit het in een aparte installatiestap, en wordt het model pas geladen als iemand echt een
stem inschrijft of laat herkennen.

Alles loopt via `SpeakerEncoder`. Daardoor kunnen de tests er een voorspelbare namaakversie
in schuiven — geen model downloaden, geen torch, geen wachten — en kan er later een andere
implementatie (pyannote) naast zonder dat de service verandert.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

import anyio

from app.utils.audio import TARGET_SAMPLE_RATE, AudioClip
from app.utils.embeddings import l2_normalize

logger = logging.getLogger("ganz.voice")

DEFAULT_MODEL = "speechbrain/spkrec-ecapa-voxceleb"


class SpeakerEncoderUnavailableError(RuntimeError):
    """Het herkenmodel kan niet geladen worden. De tekst is bedoeld voor de gebruiker."""


@runtime_checkable
class SpeakerEncoder(Protocol):
    @property
    def model_name(self) -> str:
        """Welk model de afdrukken maakt.

        Komt mee in het profiel: afdrukken van twee modellen zijn onvergelijkbaar, dus je
        moet kunnen zien waarmee er is ingeschreven.
        """

    async def embed(self, clip: AudioClip) -> list[float]:
        """Zet een fragment om in een afdruk van lengte 1."""


class SpeechBrainEncoder:
    """SpeechBrain, geladen bij het eerste gebruik en daarna hergebruikt."""

    def __init__(self, model_name: str = DEFAULT_MODEL, cache_dir: str | None = None) -> None:
        self._model_name = model_name
        self._cache_dir = cache_dir
        self._classifier: Any | None = None
        # Twee verzoeken tegelijk mogen het model niet allebei gaan laden.
        self._lock = anyio.Lock()

    @property
    def model_name(self) -> str:
        return self._model_name

    async def embed(self, clip: AudioClip) -> list[float]:
        classifier = await self._ensure_loaded()
        # Het rekenwerk is gewoon werk voor de processor en houdt de hele app op zolang het
        # duurt. Daarom naar een aparte draad, zodat andere verzoeken door kunnen.
        afdruk = await anyio.to_thread.run_sync(self._embed_sync, classifier, clip)
        return l2_normalize(afdruk)

    async def _ensure_loaded(self) -> Any:
        if self._classifier is not None:
            return self._classifier
        async with self._lock:
            if self._classifier is None:
                self._classifier = await anyio.to_thread.run_sync(self._load_sync)
        return self._classifier

    def _load_sync(self) -> Any:
        try:
            from speechbrain.inference.speaker import EncoderClassifier
        except ImportError as exc:  # pragma: no cover - hangt van de installatie af
            raise SpeakerEncoderUnavailableError(
                "Stemherkenning is niet geïnstalleerd. Installeer het eenmalig met: "
                "pip install -r requirements-voice.txt (dat haalt torch en SpeechBrain op, "
                "samen ruim een gigabyte)."
            ) from exc

        logger.info("Herkenmodel %s wordt geladen; de eerste keer duurt dat even.", self._model_name)
        try:
            return EncoderClassifier.from_hparams(
                source=self._model_name, savedir=self._cache_dir, run_opts={"device": "cpu"}
            )
        except Exception as exc:  # pragma: no cover - netwerk of schijf
            raise SpeakerEncoderUnavailableError(
                f"Het herkenmodel ({self._model_name}) kon niet geladen worden: {exc}. "
                "De eerste keer wordt het van internet gehaald; controleer de verbinding."
            ) from exc

    def _embed_sync(self, classifier: Any, clip: AudioClip) -> list[float]:
        import torch

        golf = torch.from_numpy(clip.samples).unsqueeze(0)
        if clip.sample_rate != TARGET_SAMPLE_RATE:
            import torchaudio

            golf = torchaudio.functional.resample(golf, clip.sample_rate, TARGET_SAMPLE_RATE)
        with torch.no_grad():
            afdruk = classifier.encode_batch(golf)
        return [float(w) for w in afdruk.squeeze().tolist()]
