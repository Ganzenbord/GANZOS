"""Start de Scout als eigen proces.

    GANZ_DATABASE_URL=... python -m scripts.quant_scout --source synthetic --minutes 60

Waarom een eigen proces en niet een taak in de API: de scheduler van de API draait in
hetzelfde proces als de verzoeken, en zijn jobstore zit in het geheugen. Een ingest die
daar in hangt, concurreert met het bedienen van de app en laat na elke herstart een gat
achter dat je nooit meer kunt vullen. Voor de server staat er een systemd-unit in
`deploy/ganz-quant-scout.service`.

Er is op dit moment **geen echte databron aangesloten**: de netwerkpolicy van de omgeving
laat geen enkele marktbron door (zie docs/quant-lab/phase2-report.md). Wat er wel is:
`synthetic` (verzonnen data, om de machinerie te kunnen draaien en bewijzen) en `jsonl`
(een opname van schijf). Een echte bron is één klasse die `FeedSource` implementeert.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
from datetime import datetime, timedelta, timezone

from app.core.config import get_settings
from app.core.database import create_database
from app.quantlab.feed import JsonlFileSource
from app.quantlab.scout import DEFAULT_HEARTBEAT_SECONDS, Scout
from app.quantlab.synthetic import SyntheticPoolSource

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("ganz.quantlab.scout")


def maak_bron(args: argparse.Namespace):
    if args.source == "synthetic":
        return SyntheticPoolSource(
            seed=args.seed,
            start_at=datetime.now(timezone.utc),
            duration=timedelta(minutes=args.minutes),
            pools=args.pools,
            cadence_seconds=args.cadence,
        )
    if args.source == "jsonl":
        if not args.path:
            raise SystemExit("--path is verplicht bij --source jsonl")
        return JsonlFileSource(args.path, source=args.name or "recorded")
    raise SystemExit(f"Onbekende bron: {args.source}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="De Scout van het Quant Lab")
    parser.add_argument("--source", default="synthetic", choices=("synthetic", "jsonl"))
    parser.add_argument("--path", help="bestand bij --source jsonl")
    parser.add_argument("--name", help="hoe de bron in de database heet bij --source jsonl")
    parser.add_argument("--minutes", type=int, default=60)
    parser.add_argument("--pools", type=int, default=3)
    parser.add_argument("--cadence", type=int, default=10)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--batch-size", type=int, default=200)
    parser.add_argument(
        "--heartbeat-seconds", type=float, default=DEFAULT_HEARTBEAT_SECONDS
    )
    args = parser.parse_args()

    database = create_database(get_settings())
    scout = Scout(
        database,
        source=maak_bron(args),
        batch_size=args.batch_size,
        heartbeat_seconds=args.heartbeat_seconds,
    )

    stop = asyncio.Event()
    lus = asyncio.get_running_loop()
    for teken in (signal.SIGINT, signal.SIGTERM):
        # Netjes stoppen in plaats van halverwege een batch afgebroken worden: dan staat de
        # run dicht met een reden en klopt de boekhouding van het corpus.
        lus.add_signal_handler(teken, stop.set)

    try:
        uitslag = await scout.run(stop=stop)
        logger.info(
            "Run %s: %s events, %s ticks, %s onleesbaar, %s bytes (%s)",
            uitslag.run_id,
            uitslag.events,
            uitslag.ticks,
            uitslag.parse_failures,
            uitslag.bytes_stored,
            uitslag.stop_reason,
        )
    finally:
        await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())
