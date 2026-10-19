import pytest

from jdy_feishu_sync.services.feishu_fields import FeishuFieldSerializationError, serialize_feishu_fields
from jdy_feishu_sync.services.journal import ExecutionJournal
from jdy_feishu_sync.services.sync_executor import SyncExecutor
from jdy_feishu_sync.services.sync_planner import SyncOperation, SyncPlan


METADATA = [
    {"field_id": "fld_id", "field_name": "jdy_id", "type": 1},
    {"field_id": "fld_deleted", "field_name": "jdy_deleted", "type": 7},
    {"field_id": "fld_business", "field_name": "Renamed PI Code", "type": 1},
]


def test_serializes_ids_to_current_names_including_system_fields():
    assert serialize_feishu_fields({"fld_id": "s1", "fld_deleted": False, "fld_business": "PLA01"}, METADATA) == {"jdy_id": "s1", "jdy_deleted": False, "Renamed PI Code": "PLA01"}


def test_renamed_field_keeps_id_authorization():
    assert serialize_feishu_fields({"fld_business": "PLA01"}, METADATA) == {"Renamed PI Code": "PLA01"}


def test_unknown_id_and_duplicate_name_fail_closed():
    with pytest.raises(FeishuFieldSerializationError, match="Unknown"):
        serialize_feishu_fields({"missing": "x"}, METADATA)
    duplicate = METADATA + [{"field_id": "other", "field_name": "jdy_id", "type": 1}]
    with pytest.raises(FeishuFieldSerializationError, match="Duplicate"):
        serialize_feishu_fields({"fld_id": "s1"}, duplicate)


def test_invalid_value_and_unapproved_protected_key_are_not_serialized():
    with pytest.raises(FeishuFieldSerializationError, match="boolean"):
        serialize_feishu_fields({"fld_deleted": "false"}, METADATA)
    with pytest.raises(FeishuFieldSerializationError, match="Unknown"):
        serialize_feishu_fields({"protected_field": "secret"}, METADATA)


def test_serialization_failure_prevents_http_write(tmp_path):
    class Client:
        writes = 0

        def list_fields(self):
            return METADATA

        def create_record(self, fields, *, client_token):
            self.writes += 1
            raise AssertionError("HTTP write must not be reached")

    operation = SyncOperation("op", "CREATE", "s1", None, {"stale_id": "x"})
    plan = SyncPlan("plan", "mapping", 1, 0, 0, 0, True, (operation,))
    journal = ExecutionJournal(tmp_path / "journal.sqlite")
    client = Client()
    try:
        with pytest.raises(FeishuFieldSerializationError):
            SyncExecutor(client, journal).apply(plan, confirm_write=True)
        assert client.writes == 0
    finally:
        journal.close()
