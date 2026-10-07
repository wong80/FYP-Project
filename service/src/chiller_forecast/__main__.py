"""Command line: ``python -m chiller_forecast <command>`` (also installed as ``chiller``)."""

from __future__ import annotations

import argparse
import logging
import sys

import pandas as pd

from . import db
from .settings import Env, Guardrails


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="chiller", description="Chiller power forecasting service")
    parser.add_argument("--guardrails", help="path to guardrails.yaml (default: $GUARDRAILS_PATH or bundled)")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="create tables (idempotent)")

    p = sub.add_parser("ingest-excel", help="backfill hourly readings from an Excel export")
    p.add_argument("path")
    p.add_argument("--source", default="building_meter")

    p = sub.add_parser("ingest-firebase", help="pull ESP32 readings from Firebase RTDB")
    p.add_argument("--source", default="esp32")

    p = sub.add_parser("train", help="train a challenger and apply the promotion gates")
    p.add_argument("--force", action="store_true", help="ignore the minimum-new-data rule (T4)")

    p = sub.add_parser("promote", help="make a model version the live champion (or roll back)")
    p.add_argument("version")
    p.add_argument("--reason", default="manual approval")

    sub.add_parser("score", help="forecast the coming hour")

    p = sub.add_parser("replay", help="simulate live forecasts over past hours (stored as role 'replay')")
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--version", help="model version (default: champion)")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    guardrails = Guardrails.load(args.guardrails)
    env = Env.load()
    engine = db.make_engine(env.database_url)

    if args.command == "init-db":
        db.init_schema(engine)
        print("schema ready")
    elif args.command == "ingest-excel":
        from .ingest import ingest_frame, read_excel

        print(ingest_frame(engine, args.source, read_excel(args.path), guardrails))
    elif args.command == "ingest-firebase":
        from .ingest import fetch_firebase, firebase_to_hourly, ingest_frame, now_local

        if not env.firebase_db_url:
            print("firebase not configured (FIREBASE_DB_URL unset); skipping")
            return 0
        now = now_local()
        frame = firebase_to_hourly(fetch_firebase(env), guardrails.firebase, now)
        print(ingest_frame(engine, args.source, frame, guardrails, now=now))
    elif args.command == "train":
        from .train import outcome_json, train

        outcome = train(engine, env, guardrails, force=args.force)
        print(outcome_json(outcome))
        return 0 if outcome.status in ("promoted", "challenger", "skipped") else 2
    elif args.command == "promote":
        from .train import promote

        promote(engine, env, args.version, reason=args.reason)
        print(f"v{args.version} is now champion")
    elif args.command == "score":
        from .score import score

        out = score(engine, env, guardrails)
        print(f"{out.target_ts}: {out.written or 'nothing written'} {out.note}".rstrip())
    elif args.command == "replay":
        from .score import replay

        n = replay(engine, env, guardrails, pd.Timestamp(args.start), pd.Timestamp(args.end), args.version)
        print(f"{n} replay forecasts written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
