from __future__ import annotations

import argparse
import logging
import json
import sys
from pathlib import Path

import yaml

from jdy_feishu_sync.adapters.feishu import FeishuClient
from jdy_feishu_sync.adapters.jiandaoyun import JiandaoyunClient
from jdy_feishu_sync.config import ConfigError, FeishuSettings, Settings
from jdy_feishu_sync.services.field_discovery import compare_fields
from jdy_feishu_sync.services.field_ownership import FieldOwnershipError, FieldOwnershipPolicy, ManagedField


def _feishu_client() -> FeishuClient:
    return FeishuClient(FeishuSettings.from_env())


def _source_client() -> JiandaoyunClient:
    return JiandaoyunClient(Settings.from_env())


def _mapping(path: Path) -> FieldOwnershipPolicy:
    if not path.is_file():
        raise ConfigError(f"Mapping file not found: {path}")
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = payload.get("managed_fields", [])
    if not isinstance(entries, list):
        raise ConfigError("managed_fields must be a list")
    return FieldOwnershipPolicy([ManagedField(str(item["source_id"]), str(item["target_id"]), item.get("transform")) for item in entries if isinstance(item, dict)])


def _fields_for_source(client: JiandaoyunClient, settings: Settings) -> list[dict]:
    entries = client.list_entries()
    if not any(item.get("entry_id") == settings.entry_id for item in entries):
        raise RuntimeError(f"Target entry not found: {settings.entry_id}")
    return client.get_widgets()


def _p1_command(args: argparse.Namespace) -> int:
    if args.command == "feishu-check":
        with _feishu_client() as client:
            table = client.get_table(); fields = client.list_fields()
            print(f"OK: {table.get('name', 'Feishu table')} ({len(fields)} fields)")
        return 0
    if args.command == "feishu-inspect-fields":
        with _feishu_client() as client:
            for field in client.list_fields():
                print(f"{field.get('field_name', '')}\t{field.get('field_id', '')}\t{field.get('type', '')}")
        return 0
    if args.command == "feishu-inspect-records":
        with _feishu_client() as client:
            page = client.list_records(page_size=max(args.limit, 1))
            records = page["items"][:args.limit]
            print(f"records: {len(records)}")
            for record in records:
                print(f"{record.get('record_id')}\t{', '.join(sorted((record.get('fields') or {}).keys()))}")
        return 0
    if args.command == "feishu-count-records":
        with _feishu_client() as client:
            print(sum(1 for _ in client.iter_all_records()))
        return 0
    if args.command in {"compare-fields", "export-field-mapping"}:
        source_settings = Settings.from_env()
        with _source_client() as source, _feishu_client() as target:
            target_fields = target.list_fields()
            candidates = compare_fields(_fields_for_source(source, source_settings), target_fields)
        if args.command == "compare-fields":
            for item in candidates:
                print(f"{item.source_label}\t{item.target_name or '-'}\t{item.compatibility}\t{item.status}")
            matched_target_ids = {item.target_id for item in candidates if item.target_id}
            for field in target_fields:
                if str(field.get("field_id", "")) not in matched_target_ids:
                    print(f"-\t{field.get('field_name', '')}\ttarget_only\tprotected")
            return 0
        output = args.output
        if output.exists() and not args.force:
            raise RuntimeError(f"Refusing to overwrite existing file: {output}; use --force")
        output.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "identity": {"source_record_id": "_id", "target_record_id_field": "jdy_id"}, "fields": [{**item.to_dict(), "enabled": False, "transform": None} for item in candidates]}
        output.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
        print(f"Wrote {output}")
        return 0
    if args.command == "validate-field-mapping":
        source_settings = Settings.from_env(); policy = _mapping(args.mapping)
        with _source_client() as source, _feishu_client() as target:
            policy.validate_mapping(_fields_for_source(source, source_settings), target.list_fields())
        print("Field mapping is valid")
        return 0
    if args.command == "preview-update":
        source_settings = Settings.from_env(); policy = _mapping(args.mapping)
        with _source_client() as source, _feishu_client() as target:
            source_fields = _fields_for_source(source, source_settings); target_fields = target.list_fields()
            policy.validate_mapping(source_fields, target_fields)
            record = next((item for item in source.iter_all_records() if item.get("_id") == args.record_id), None)
            if record is None:
                raise RuntimeError(f"Jiandaoyun record not found: {args.record_id}")
            print(json.dumps({"record_id": args.record_id, "fields_to_update": sorted(policy.build_update_fields(record).keys()), "write_performed": False}, ensure_ascii=False, indent=2))
        return 0
    return -1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jdy-sync")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check")
    sub.add_parser("inspect-fields")
    records = sub.add_parser("inspect-records")
    records.add_argument("--limit", type=int, default=5)
    sub.add_parser("count-records")
    sub.add_parser("verify")
    sub.add_parser("feishu-check")
    sub.add_parser("feishu-inspect-fields")
    records = sub.add_parser("feishu-inspect-records")
    records.add_argument("--limit", type=int, default=5)
    sub.add_parser("feishu-count-records")
    sub.add_parser("compare-fields")
    export = sub.add_parser("export-field-mapping")
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--force", action="store_true")
    validate = sub.add_parser("validate-field-mapping")
    validate.add_argument("--mapping", type=Path, default=Path("config/field_mapping.yaml"))
    preview = sub.add_parser("preview-update")
    preview.add_argument("--record-id", required=True)
    preview.add_argument("--mapping", type=Path, default=Path("config/field_mapping.yaml"))
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _parser().parse_args(argv)
    try:
        if args.command.startswith("feishu-") or args.command in {"compare-fields", "export-field-mapping", "validate-field-mapping", "preview-update"}:
            return _p1_command(args)
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
