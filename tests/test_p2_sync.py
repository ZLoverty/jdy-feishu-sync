import pytest

from jdy_feishu_sync.services.field_ownership import FieldOwnershipPolicy, ManagedField
from jdy_feishu_sync.services.sync_executor import SyncExecutionError, SyncExecutor
from jdy_feishu_sync.services.sync_planner import SyncPlanner


def policy():
    value = FieldOwnershipPolicy([ManagedField("name", "fld_name", "text")], {"jdy_id": "fld_id", "jdy_deleted": "fld_deleted", "jdy_updated_at": "fld_updated", "synced_at": "fld_synced"})
    value.validate_mapping([{"name": "name"}], [{"field_id": "fld_id", "field_name": "jdy_id", "type": 1}, {"field_id": "fld_deleted", "field_name": "jdy_deleted", "type": 7}, {"field_id": "fld_updated", "field_name": "jdy_updated_at", "type": 5}, {"field_id": "fld_synced", "field_name": "synced_at", "type": 5}, {"field_id": "fld_name", "field_name": "Name", "type": 1}])
    return value


def test_planner_updates_only_managed_fields_and_skips_protected_difference():
    mapping = policy()
    source = [{"_id": "s1", "name": "new"}]
    target = [{"record_id": "r1", "fields": {"fld_id": "s1", "fld_name": "old", "protected": "operator value"}}]
    plan = SyncPlanner().build_plan(source, target, mapping)
    assert plan.counts["UPDATE"] == 1
    assert plan.operations[0].fields == {"fld_name": "new"}


def test_empty_target_creates_every_source_record():
    plan = SyncPlanner().build_plan([{"_id": "s1", "name": "x"}, {"_id": "s2", "name": "y"}], [], policy())
    assert plan.counts["CREATE"] == 2
    assert plan.counts["UPDATE"] == plan.counts["SKIP"] == plan.counts["BLOCK"] == 0


def test_duplicate_target_identity_blocks():
    target = [{"record_id": "r1", "fields": {"fld_id": "s1"}}, {"record_id": "r2", "fields": {"fld_id": "s1"}}]
    plan = SyncPlanner().build_plan([{"_id": "s1", "name": "x"}], target, policy())
    assert plan.counts["BLOCK"] >= 1


def test_system_field_error_explains_actual_and_expected_type():
    mapping = policy()
    fields = [{"field_id": "fld_id", "field_name": "jdy_id", "type": 1}, {"field_id": "fld_deleted", "field_name": "jdy_deleted", "type": 1}]
    with pytest.raises(ValueError, match="actual Text.*expected Checkbox"):
        mapping.validate_system_fields(fields)


def test_executor_requires_explicit_write_confirmation(tmp_path):
    journal = __import__("jdy_feishu_sync.services.journal", fromlist=["ExecutionJournal"]).ExecutionJournal(tmp_path / "journal.sqlite")
    try:
        plan = SyncPlanner().build_plan([], [], policy())
        with pytest.raises(SyncExecutionError, match="confirm-write"):
            SyncExecutor(object(), journal).apply(plan, confirm_write=False)
    finally:
        journal.close()
