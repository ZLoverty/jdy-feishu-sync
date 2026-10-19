from __future__ import annotations

import json
import os
from pathlib import Path

from jdy_feishu_sync.adapters.feishu import FeishuError, FeishuRepeatedRequestError

from .journal import ExecutionJournal
from .feishu_fields import serialize_feishu_fields
from .sync_planner import SyncPlan


class SyncExecutionError(RuntimeError):
    pass


class LocalExecutionLock:
    def __init__(self, path: Path):
        self.path = path

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise SyncExecutionError(f"Another local synchronization is running: {self.path}") from exc
        os.write(self.fd, str(os.getpid()).encode())
        return self

    def __exit__(self, *_):
        os.close(self.fd)
        self.path.unlink(missing_ok=True)


class SyncExecutor:
    def __init__(self, client, journal: ExecutionJournal):
        self.client = client
        self.journal = journal

    def apply(self, plan: SyncPlan, *, confirm_write: bool, batch_size: int = 10) -> dict[str, int]:
        if not confirm_write:
            raise SyncExecutionError("Refusing to write without --confirm-write")
        if not plan.complete or plan.counts["BLOCK"]:
            raise SyncExecutionError("Plan contains blocking operations or is incomplete")
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        live_field_metadata = self.client.list_fields()
        result = {"SUCCEEDED": 0, "FAILED": 0, "UNCERTAIN": 0, "SKIP": 0}
        for operation in plan.operations:
            client_token = self.journal.prepare(plan.plan_id, operation.operation_id, operation.source_id, operation.target_id, operation.action)
            if operation.action == "SKIP":
                result["SKIP"] += 1; continue
            self.journal.start(plan.plan_id, operation.operation_id)
            try:
                if operation.action == "CREATE":
                    if not client_token:
                        raise SyncExecutionError(f"CREATE operation {operation.operation_id} has no persisted client_token")
                    serialized = serialize_feishu_fields(operation.fields, live_field_metadata)
                    record = self.client.create_record(serialized, client_token=client_token)
                elif operation.action == "UPDATE":
                    serialized = serialize_feishu_fields(operation.fields, live_field_metadata)
                    record = self.client.update_record(operation.target_id, serialized)
                else:
                    raise SyncExecutionError(f"Unsupported action: {operation.action}")
                if not isinstance(record, dict):
                    raise SyncExecutionError("Feishu write returned an invalid record")
                self.journal.finish(plan.plan_id, operation.operation_id, "SUCCEEDED")
                result["SUCCEEDED"] += 1
            except TimeoutError:
                self.journal.finish(plan.plan_id, operation.operation_id, "UNCERTAIN", "timeout")
                result["UNCERTAIN"] += 1
                raise SyncExecutionError(f"Uncertain outcome for {operation.operation_id}; reconcile before retrying")
            except FeishuRepeatedRequestError as exc:
                if operation.action != "CREATE":
                    self.journal.finish(plan.plan_id, operation.operation_id, "BLOCKED", "repeated_request")
                    raise SyncExecutionError(f"Repeated request rejected for non-CREATE operation {operation.operation_id}") from exc
                try:
                    recovered = self._recover_create(operation)
                except SyncExecutionError:
                    self.journal.finish(plan.plan_id, operation.operation_id, "BLOCKED", "duplicate_identity")
                    result["UNCERTAIN"] += 1
                    raise
                if recovered:
                    self.journal.finish(plan.plan_id, operation.operation_id, "SUCCEEDED", "recovered_repeated_request")
                    result["SUCCEEDED"] += 1
                    continue
                self.journal.finish(plan.plan_id, operation.operation_id, "BLOCKED", "repeated_request_target_not_found")
                result["UNCERTAIN"] += 1
                raise SyncExecutionError(f"Repeated CREATE request unresolved for {operation.source_id}; no exact jdy_id match") from exc
            except FeishuError as exc:
                if operation.action == "CREATE" and ("Network error" in str(exc) or "timeout" in str(exc).lower()):
                    recovered = self._recover_create(operation)
                    if recovered:
                        self.journal.finish(plan.plan_id, operation.operation_id, "SUCCEEDED", "recovered_after_uncertain_create")
                        result["SUCCEEDED"] += 1
                        continue
                    self.journal.finish(plan.plan_id, operation.operation_id, "UNCERTAIN", "create_outcome_unknown")
                    result["UNCERTAIN"] += 1
                    raise SyncExecutionError(f"Uncertain CREATE outcome for {operation.operation_id}; operator review required") from exc
                self.journal.finish(plan.plan_id, operation.operation_id, "FAILED", type(exc).__name__)
                result["FAILED"] += 1
                raise
            except Exception as exc:
                self.journal.finish(plan.plan_id, operation.operation_id, "FAILED", type(exc).__name__)
                result["FAILED"] += 1
                raise
        return result

    def _recover_create(self, operation) -> bool:
        records = list(self.client.iter_all_records())
        metadata = self.client.list_fields()
        serialized = serialize_feishu_fields(operation.fields, metadata)
        identity_key = next((field["field_name"] for field in metadata if field.get("field_id") == next(iter(operation.fields), None)), None)
        matches = [item for item in records if isinstance(item.get("fields"), dict) and identity_key and item["fields"].get(identity_key) == operation.source_id]
        if len(matches) > 1:
            raise SyncExecutionError(f"Multiple Feishu records found for uncertain CREATE {operation.source_id}")
        if not matches:
            return False
        fields = matches[0]["fields"]
        return all(fields.get(key) == value for key, value in serialized.items())


def write_plan(path: Path, plan: SyncPlan) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def read_plan(path: Path) -> SyncPlan:
    if not path.is_file():
        raise SyncExecutionError(f"Plan file not found: {path}")
    return SyncPlan.from_dict(json.loads(path.read_text(encoding="utf-8")))
