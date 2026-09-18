"""Systeemmonitor: echte metingen via psutil.

De grafiek op het dashboard komt uit een ringbuffer die de scheduler vult. Die staat
bewust in het geheugen: het zijn wegwerpgegevens en het zou zonde zijn om er elke
paar seconden de database mee te belasten.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime
from typing import Any

import psutil

from app.models.base import utcnow

HISTORY_SIZE = 60
_history: deque[dict[str, Any]] = deque(maxlen=HISTORY_SIZE)


def sample() -> dict[str, Any]:
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    # interval=None geeft het gemiddelde sinds de vorige aanroep; met een interval
    # zou elke dashboardrefresh een seconde blijven hangen.
    return {
        "cpu_pct": round(psutil.cpu_percent(interval=None), 1),
        "ram_pct": round(memory.percent, 1),
        "disk_pct": round(disk.percent, 1),
        "measured_at": utcnow(),
    }


def record_sample() -> dict[str, Any]:
    reading = sample()
    _history.append(reading)
    return reading


def snapshot(*, detailed: bool = True) -> dict[str, Any]:
    """De toestand van de machine.

    Zonder `detailed` alleen het stoplicht: draait alles nog, ja of nee. De cijfers zelf
    (belasting, schijfruimte, hoe lang de machine al aanstaat) zeggen meer over de computer
    dan over Ganz en zijn alleen voor tier 1. Zonder dit onderscheid zou de tier-1-eis op
    /system/metrics niets voorstellen: dezelfde getallen stonden dan gewoon in /system.
    """
    current = record_sample()
    warnings = [
        name
        for name, value in (
            ("CPU", current["cpu_pct"]),
            ("geheugen", current["ram_pct"]),
            ("schijf", current["disk_pct"]),
        )
        if value >= 90
    ]
    status = {
        "status": "warning" if warnings else "optimal",
        "status_detail": (
            f"Hoge belasting: {', '.join(warnings)}" if warnings else "Alles optimaal"
        ),
        "measured_at": current["measured_at"],
    }
    if not detailed:
        return status
    return {
        **current,
        **status,
        "history": list(_history),
        "boot_time": datetime.fromtimestamp(psutil.boot_time()).astimezone(),
    }
