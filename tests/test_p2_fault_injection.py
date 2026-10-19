import pytest
import uuid

from jdy_feishu_sync.adapters.feishu import FeishuError, FeishuRepeatedRequestError
from jdy_feishu_sync.services.field_ownership import FieldOwnershipPolicy
from jdy_feishu_sync.services.journal import ExecutionJournal
from jdy_feishu_sync.services.sync_executor import SyncExecutionError, SyncExecutor
from jdy_feishu_sync.services.sync_planner import SyncOperation, SyncPlan, SyncPlanner
from jdy_feishu_sync.services.recovery import diagnose_create


def make_plan(*operations):
    return SyncPlan("plan", "mapping", 0, 0, 0, 0, True, tuple(operations))


def fields():
    return [{"field_id": "fld_id", "field_name": "jdy_id", "type": 1}, {"field_id": "fld_deleted", "field_name": "jdy_deleted", "type": 7}, {"field_id": "fld_name", "field_name": "Name", "type": 1}]


def test_uncertain_create_is_recovered_by_exact_identity(tmp_path):
    class Client:
        tokens = []

        def list_fields(self):
            return fields()

        def create_record(self, fields, *, client_token):
            raise FeishuError("Network error calling records: timeout")
            raise FeishuError("Network error calling records: timeout")

        def iter_all_records(self):
            return iter([{"record_id": "rec1", "fields": {"jdy_id": "s1", "jdy_deleted": False}}])

    op = SyncOperation("op1", "CREATE", "s1", None, {"fld_id": "s1", "fld_deleted": False})
    journal = ExecutionJournal(tmp_path / "journal.sqlite")
    try:
        result = SyncExecutor(Client(), journal).apply(make_plan(op), confirm_write=True)
        assert result["SUCCEEDED"] == 1
        assert journal.unresolved() == []
    finally:
        journal.close()


def test_update_timeout_is_uncertain(tmp_path):
    class Client:
        def list_fields(self):
            return fields()

        def update_record(self, record_id, fields):
            raise TimeoutError("timeout")

    op = SyncOperation("op1", "UPDATE", "s1", "rec1", {"fld_name": "new"})
    journal = ExecutionJournal(tmp_path / "journal.sqlite")
    try:
        with pytest.raises(SyncExecutionError, match="Uncertain outcome"):
            SyncExecutor(Client(), journal).apply(make_plan(op), confirm_write=True)
        assert journal.unresolved()[0][5] == "UNCERTAIN"
    finally:
        journal.close()


def test_partial_failure_is_journaled(tmp_path):
    class Client:
        calls = 0

        def list_fields(self):
            return fields()

        def create_record(self, fields, *, client_token):
            self.calls += 1
            if self.calls == 2:
                raise FeishuError("permission denied")
            return {"record_id": fields["jdy_id"]}

    ops = (SyncOperation("op1", "CREATE", "s1", None, {"fld_id": "s1"}), SyncOperation("op2", "CREATE", "s2", None, {"fld_id": "s2"}))
    journal = ExecutionJournal(tmp_path / "journal.sqlite")
    try:
        with pytest.raises(FeishuError):
            SyncExecutor(Client(), journal).apply(make_plan(*ops), confirm_write=True)
        states = [row[6] for row in journal.db.execute("SELECT * FROM operations ORDER BY operation_id")]
        assert states == ["SUCCEEDED", "FAILED"]
    finally:
        journal.close()


def test_create_tokens_are_distinct_uuid4_and_persisted(tmp_path):
    class Client:
        tokens = []

        def list_fields(self):
            return fields()

        def create_record(self, fields, *, client_token):
            self.tokens.append(client_token)
            return {"record_id": fields["jdy_id"]}

    client = Client()
    ops = (SyncOperation("op1", "CREATE", "s1", None, {"fld_id": "s1"}), SyncOperation("op2", "CREATE", "s2", None, {"fld_id": "s2"}))
    journal = ExecutionJournal(tmp_path / "journal.sqlite")
    try:
        SyncExecutor(client, journal).apply(make_plan(*ops), confirm_write=True)
        assert len(set(client.tokens)) == 2
        assert all(uuid.UUID(token).version == 4 for token in client.tokens)
        assert client.tokens[0] != "plan"
        assert journal.client_token("plan", "op1") == client.tokens[0]
    finally:
        journal.close()


def test_restart_reuses_persisted_create_token(tmp_path):
    path = tmp_path / "journal.sqlite"
    first = ExecutionJournal(path)
    first_token = first.prepare("plan", "op1", "s1", None, "CREATE")
    first.close()
    second = ExecutionJournal(path)
    try:
        assert second.prepare("plan", "op1", "s1", None, "CREATE") == first_token
        assert second.client_token("plan", "op1") == first_token
    finally:
        second.close()


def test_repeated_request_recovers_existing_exact_identity(tmp_path):
    class Client:
        def list_fields(self):
            return fields()

        def create_record(self, fields, *, client_token):
            raise FeishuRepeatedRequestError(403, "Same API requests are submitted repeatedly")

        def iter_all_records(self):
            return iter([{"record_id": "rec1", "fields": {"jdy_id": "s1", "jdy_deleted": False}}])

    op = SyncOperation("op1", "CREATE", "s1", None, {"fld_id": "s1", "fld_deleted": False})
    journal = ExecutionJournal(tmp_path / "journal.sqlite")
    try:
        assert SyncExecutor(Client(), journal).apply(make_plan(op), confirm_write=True)["SUCCEEDED"] == 1
        assert journal.unresolved() == []
    finally:
        journal.close()


def test_repeated_request_without_target_is_blocked_without_replay(tmp_path):
    class Client:
        calls = 0

        def list_fields(self):
            return fields()

        def create_record(self, fields, *, client_token):
            self.calls += 1
            raise FeishuRepeatedRequestError(403, "Same API requests are submitted repeatedly")

        def iter_all_records(self):
            return iter([])

    client = Client()
    op = SyncOperation("op1", "CREATE", "s1", None, {"fld_id": "s1", "fld_deleted": False})
    journal = ExecutionJournal(tmp_path / "journal.sqlite")
    try:
        with pytest.raises(SyncExecutionError, match="unresolved"):
            SyncExecutor(client, journal).apply(make_plan(op), confirm_write=True)
        assert client.calls == 1
        assert journal.db.execute("SELECT state, error_category FROM operations").fetchone() == ("BLOCKED", "repeated_request_target_not_found")
    finally:
        journal.close()


def test_repeated_request_with_duplicate_identity_blocks(tmp_path):
    class Client:
        def list_fields(self):
            return fields()

        def create_record(self, fields, *, client_token):
            raise FeishuRepeatedRequestError(403, "Same API requests are submitted repeatedly")

        def iter_all_records(self):
            return iter([
                {"record_id": "rec1", "fields": {"jdy_id": "s1", "jdy_deleted": False}},
                {"record_id": "rec2", "fields": {"jdy_id": "s1", "jdy_deleted": False}},
            ])

    op = SyncOperation("op1", "CREATE", "s1", None, {"fld_id": "s1", "fld_deleted": False})
    journal = ExecutionJournal(tmp_path / "journal.sqlite")
    try:
        with pytest.raises(SyncExecutionError, match="Multiple"):
            SyncExecutor(Client(), journal).apply(make_plan(op), confirm_write=True)
        assert journal.db.execute("SELECT state, error_category FROM operations").fetchone() == ("BLOCKED", "duplicate_identity")
    finally:
        journal.close()


def test_in_progress_operation_survives_restart(tmp_path):
    path = tmp_path / "journal.sqlite"
    first = ExecutionJournal(path)
    first.prepare("plan", "op1", "s1", None, "CREATE")
    first.start("plan", "op1")
    first.close()
    second = ExecutionJournal(path)
    try:
        assert second.unresolved()[0][5] == "IN_PROGRESS"
    finally:
        second.close()


def test_recovery_diagnosis_is_read_only_and_requires_exact_one_match(tmp_path):
    class Client:
        def list_fields(self):
            return fields()

        def iter_all_records(self):
            return iter([{"record_id": "rec1", "fields": {"jdy_id": "s1", "jdy_deleted": False}}])

    journal = ExecutionJournal(tmp_path / "journal.sqlite")
    journal.prepare("plan", "op1", "s1", None, "CREATE")
    journal.start("plan", "op1")
    before = journal.db.execute("SELECT state, attempts FROM operations").fetchone()
    try:
        report = diagnose_create(Client(), journal, "plan", "s1", "fld_id", {"fld_id": "s1", "fld_deleted": False})
        assert report["target_match_count"] == 1
        assert report["record_verified"] is True
        assert journal.db.execute("SELECT state, attempts FROM operations").fetchone() == before
    finally:
        journal.close()
