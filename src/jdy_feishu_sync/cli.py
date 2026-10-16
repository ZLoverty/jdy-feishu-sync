from __future__ import annotations

import argparse
import logging
import sys

from jdy_feishu_sync.adapters.jiandaoyun import JiandaoyunClient
from jdy_feishu_sync.config import ConfigError, Settings


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jdy-sync")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check")
    sub.add_parser("inspect-fields")
    records = sub.add_parser("inspect-records")
    records.add_argument("--limit", type=int, default=5)
    sub.add_parser("count-records")
    sub.add_parser("verify")
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _parser().parse_args(argv)
    try:
        settings = Settings.from_env()
        with JiandaoyunClient(settings) as client:
            entries = client.list_entries()
            target = next((item for item in entries if item.get("entry_id") == settings.entry_id), None)
            if args.command == "check":
                if target is None:
                    raise RuntimeError(f"Target entry not found: {settings.entry_id}")
                print(f"OK: {target.get('name', settings.entry_id)} ({settings.entry_id})")
            elif args.command == "inspect-fields":
                for widget in client.get_widgets():
                    print(f"{widget.get('label', '')}\t{widget.get('name', '')}\t{widget.get('type', '')}")
            elif args.command == "inspect-records":
                if args.limit < 0:
                    raise ValueError("--limit must not be negative")
                records = client.list_records(limit=max(args.limit, 1))[:args.limit]
                print(f"records: {len(records)}")
                for record in records:
                    print(f"{record.get('_id')}\t{', '.join(record.keys())}")
            elif args.command == "count-records":
                print(sum(1 for _ in client.iter_all_records()))
            elif args.command == "verify":
                if target is None:
                    raise RuntimeError(f"Target entry not found: {settings.entry_id}")
                client.get_widgets()
                list(client.iter_all_records())
                print("P0 verification passed")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
