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
from jdy_feishu_sync.services.journal import ExecutionJournal
from jdy_feishu_sync.services.sync_executor import LocalExecutionLock, SyncExecutor, read_plan, write_plan
from jdy_feishu_sync.services.sync_planner import SyncPlanner
from jdy_feishu_sync.services.recovery import diagnose_create
from jdy_feishu_sync.services.schema_mapping import build_proposals, load_proposals, proposal_payload, validate_proposals


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
    system = payload.get("system_fields", {})
    if not isinstance(system, dict):
        raise ConfigError("system_fields must be a mapping")
    system_ids = {str(name): str(value.get("target_id", "")) for name, value in system.items() if isinstance(value, dict)}
    return FieldOwnershipPolicy([ManagedField(str(item["source_id"]), str(item["target_id"]), item.get("transform")) for item in entries if isinstance(item, dict)], system_ids)


def _p2_snapshot(mapping: FieldOwnershipPolicy):
    source_settings = Settings.from_env()
    with _source_client() as source, _feishu_client() as target:
        source_records = list(source.iter_all_records())
        target_records = list(target.iter_all_records())
        source_fields = _fields_for_source(source, source_settings)
        target_fields = target.list_fields()
        mapping.validate_system_fields(target_fields)
        mapping.validate_mapping(source_fields, target_fields)
        return source_records, target_records


def _print_plan(plan):
    print(f"Source records: {plan.source_count}")
    print(f"Target records: {plan.target_count}")
    for action in ("CREATE", "UPDATE", "SKIP", "BLOCK"):
        print(f"{action + ':':<20}{plan.counts[action]}")
    print(f"Protected fields:     {plan.protected_field_count}")
    print(f"Legacy unlinked:      {plan.legacy_unlinked_count}")
    print("Writes performed:     0")


def _fields_for_source(client: JiandaoyunClient, settings: Settings) -> list[dict]:
    entries = client.list_entries()
    if not any(item.get("entry_id") == settings.entry_id for item in entries):
        raise RuntimeError(f"Target entry not found: {settings.entry_id}")
    return client.get_widgets()


def _p1_command(args: argparse.Namespace) -> int:
    if args.command == "schema-propose":
        source_settings = Settings.from_env()
        with _source_client() as source, _feishu_client() as target:
            source_fields = _fields_for_source(source, source_settings)
            list(source.iter_all_records())
            proposals = build_proposals(source_fields, target.list_fields())
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(yaml.safe_dump(proposal_payload(proposals), allow_unicode=True, sort_keys=False), encoding="utf-8")
        print(f"Wrote {args.output} ({len(proposals)} proposals; all approved=false)")
        return 0
    if args.command == "schema-review":
        proposals = load_proposals(args.proposal)
        errors = validate_proposals(proposals)
        counts = {action: sum(item.action == action for item in proposals) for action in ("MATCH_EXISTING", "CREATE_NEW", "UNSUPPORTED", "AMBIGUOUS", "IGNORE")}
        print(json.dumps({"counts": counts, "approved": sum(item.approved for item in proposals), "errors": errors, "read_only": True}, ensure_ascii=False, indent=2))
        return 1 if errors else 0
    if args.command == "schema-apply":
        if not args.confirm_schema_write:
            raise RuntimeError("Refusing schema writes without --confirm-schema-write")
        proposals = load_proposals(args.proposal)
        errors = validate_proposals(proposals)
        if errors:
            raise RuntimeError("Invalid schema proposal: " + "; ".join(errors))
        approved = [item for item in proposals if item.approved]
        if not approved:
            raise RuntimeError("No explicitly approved schema proposals")
        source_settings = Settings.from_env()
        mapping_payload = yaml.safe_load(args.mapping.read_text(encoding="utf-8")) or {}
        with _source_client() as source, _feishu_client() as target:
            source_fields = _fields_for_source(source, source_settings)
            live = target.list_fields()
            source_by_id = {str(item.get("name")): item for item in source_fields}
            for item in approved:
                if item.source_id not in source_by_id:
                    raise RuntimeError(f"Approved source field no longer exists: {item.source_id}")
                matches = [field for field in live if field.get("field_name") == item.target_name]
                compatible = [field for field in matches if field.get("type") == item.target_type]
                if len(matches) > 1 or (matches and not compatible):
                    raise RuntimeError(f"Existing Feishu field is ambiguous or incompatible: {item.target_name}")
                if item.action == "MATCH_EXISTING":
                    if not compatible or compatible[0].get("field_id") != item.target_id:
                        raise RuntimeError(f"Approved existing field changed: {item.source_id}")
                    target_id = item.target_id
                else:
                    if compatible:
                        target_id = compatible[0].get("field_id")
                    else:
                        target.create_field(item.target_name or item.source_label, int(item.target_type), {})
                        live = target.list_fields()
                        created = [field for field in live if field.get("field_name") == item.target_name and field.get("type") == item.target_type]
                        if len(created) != 1:
                            raise RuntimeError(f"Created field could not be uniquely reconciled: {item.target_name}")
                        target_id = created[0].get("field_id")
                managed = mapping_payload.setdefault("managed_fields", [])
                if any(entry.get("source_id") == item.source_id for entry in managed if isinstance(entry, dict)):
                    raise RuntimeError(f"Refusing to replace existing mapping: {item.source_id}")
                managed.append({"source_id": item.source_id, "target_id": target_id, "transform": item.transform})
        args.mapping.write_text(yaml.safe_dump(mapping_payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
        print(f"Updated {args.mapping}; record synchronization was not started")
        return 0
    if args.command == "validate-system-fields":
        mapping = _mapping(args.mapping)
        with _feishu_client() as client:
            mapping.validate_system_fields(client.list_fields())
        print("System field schema is valid")
        return 0
    if args.command == "sync-plan":
        mapping = _mapping(args.mapping)
        source_records, target_records = _p2_snapshot(mapping)
        plan = SyncPlanner().build_plan(source_records, target_records, mapping)
        if args.output:
            write_plan(args.output, plan); print(f"Wrote {args.output}")
        _print_plan(plan)
        return 0
    if args.command == "sync-apply":
        plan = read_plan(args.plan)
        journal = ExecutionJournal(args.journal)
        try:
            with LocalExecutionLock(args.journal.with_suffix(args.journal.suffix + ".lock")):
                with _feishu_client() as client:
                    print(json.dumps(SyncExecutor(client, journal).apply(plan, confirm_write=args.confirm_write, batch_size=args.batch_size), indent=2))
        finally:
            journal.close()
        return 0
    if args.command == "sync-status":
        journal = ExecutionJournal(args.journal)
        try:
            print(json.dumps({"summary": journal.summary(), "unresolved": journal.unresolved()}, default=str, indent=2))
        finally:
            journal.close()
        return 0
    if args.command == "sync-recover":
        mapping = _mapping(args.mapping)
        journal = ExecutionJournal(args.journal)
        try:
            plan = read_plan(args.plan) if args.plan else None
            if plan is not None and plan.plan_id != args.plan_id:
                raise RuntimeError("Recovery plan ID does not match --plan-id")
            with _feishu_client() as client:
                reports = []
                for source_id in args.source_id:
                    expected = None
                    if plan is not None:
                        operation = next((item for item in plan.operations if item.source_id == source_id), None)
                        if operation is None:
                            raise RuntimeError(f"Source ID is not present in recovery plan: {source_id}")
                        expected = operation.fields
                    reports.append(diagnose_create(client, journal, args.plan_id, source_id, mapping.system_fields["jdy_id"], expected))
            print(json.dumps({"dry_run": not args.confirm_recovery, "reports": reports}, ensure_ascii=False, indent=2))
            if args.confirm_recovery:
                if plan is None:
                    raise RuntimeError("--confirm-recovery requires --plan for field verification")
                if any(item.get("target_match_count") != 1 or not item.get("record_verified") for item in reports):
                    raise RuntimeError("Recovery refused: every operation must have exactly one verified target record")
                for item in reports:
                    journal.finish(args.plan_id, item["operation_id"], "SUCCEEDED", "recovered_by_exact_jdy_id")
        finally:
            journal.close()
        return 0
    if args.command == "sync-verify":
        mapping = _mapping(args.mapping); source_records, target_records = _p2_snapshot(mapping)
        target_by_id = {mapping.field_value(item, mapping.system_fields["jdy_id"]): item for item in target_records}
        mismatches = []
        for source in source_records:
            target = target_by_id.get(source.get("_id"))
            if not target:
                mismatches.append({"source_id": source.get("_id"), "reason": "missing target"}); continue
            for field_id, value in mapping.build_update_fields(source).items():
                if mapping.field_value(target, field_id) != value:
                    mismatches.append({"source_id": source.get("_id"), "field_id": field_id})
        print(json.dumps({"source_count": len(source_records), "target_count": len(target_records), "mismatches": mismatches}, ensure_ascii=False, indent=2))
        return 1 if mismatches else 0
    if args.command == "feishu-check":
        with _feishu_client() as client:
            table = client.get_table(); fields = client.list_fields()
            print(f"OK: {table.get('name', 'Feishu table')} ({len(fields)} fields)")
        return 0
    if args.command == "feishu-inspect-fields":
        with _feishu_client() as client:
            for field in client.list_fields():
                print(f"{field.get('field_name', '')}\t{field.get('field_id', '')}\t{field.get('type', '')}\t{field.get('ui_type', '')}")
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
    for command in ("validate-system-fields", "sync-verify"):
        item = sub.add_parser(command)
        item.add_argument("--mapping", type=Path, default=Path("config/field_mapping.yaml"))
    plan = sub.add_parser("sync-plan")
    plan.add_argument("--output", type=Path)
    plan.add_argument("--mapping", type=Path, default=Path("config/field_mapping.yaml"))
    apply = sub.add_parser("sync-apply")
    apply.add_argument("--plan", type=Path, required=True)
    apply.add_argument("--confirm-write", action="store_true")
    apply.add_argument("--batch-size", type=int, default=10)
    apply.add_argument("--journal", type=Path, default=Path("tmp/p2-execution.sqlite"))
    status = sub.add_parser("sync-status")
    status.add_argument("--journal", type=Path, default=Path("tmp/p2-execution.sqlite"))
    recover = sub.add_parser("sync-recover")
    recover.add_argument("--plan-id", required=True)
    recover.add_argument("--plan", type=Path)
    recover.add_argument("--source-id", action="append", required=True)
    recover.add_argument("--journal", type=Path, default=Path("tmp/p2-execution.sqlite"))
    recover.add_argument("--mapping", type=Path, default=Path("config/field_mapping.yaml"))
    recover.add_argument("--confirm-recovery", action="store_true", help="reserved; recovery mutations are disabled in this hotfix")
    proposal = sub.add_parser("schema-propose")
    proposal.add_argument("--output", type=Path, required=True)
    review = sub.add_parser("schema-review")
    review.add_argument("--proposal", type=Path, required=True)
    schema_apply = sub.add_parser("schema-apply")
    schema_apply.add_argument("--proposal", type=Path, required=True)
    schema_apply.add_argument("--mapping", type=Path, default=Path("config/field_mapping.yaml"))
    schema_apply.add_argument("--confirm-schema-write", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _parser().parse_args(argv)
    try:
        if args.command.startswith("feishu-") or args.command in {"compare-fields", "export-field-mapping", "validate-field-mapping", "preview-update", "validate-system-fields", "sync-plan", "sync-apply", "sync-verify", "sync-status", "sync-recover", "schema-propose", "schema-review", "schema-apply"}:
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
