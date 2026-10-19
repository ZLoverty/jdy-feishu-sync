from jdy_feishu_sync.services.feishu_fields import serialize_feishu_fields
from jdy_feishu_sync.services.field_ownership import FieldOwnershipPolicy, ManagedField
from jdy_feishu_sync.services.sync_planner import SyncPlanner


TARGET_FIELDS = [
    {"field_id": "fld_id", "field_name": "jdy_id", "type": 1},
    {"field_id": "fld_deleted", "field_name": "jdy_deleted", "type": 7},
    {"field_id": "fld_pi", "field_name": "PI Code", "type": 1},
]
SOURCE_FIELDS = [{"name": "_widget_pi", "label": "PI Code", "type": "text"}]


def approved_policy():
    policy = FieldOwnershipPolicy([ManagedField("_widget_pi", "fld_pi", "text")], {"jdy_id": "fld_id", "jdy_deleted": "fld_deleted"})
    policy.validate_mapping(SOURCE_FIELDS, TARGET_FIELDS)
    return policy


def test_create_includes_approved_business_field_and_empty_mapping_does_not():
    source = [{"_id": "s1", "_widget_pi": "PLA01"}]
    plan = SyncPlanner().build_plan(source, [], approved_policy())
    assert plan.operations[0].fields == {"fld_id": "s1", "fld_deleted": False, "fld_pi": "PLA01"}
    empty = FieldOwnershipPolicy([], {"jdy_id": "fld_id", "jdy_deleted": "fld_deleted"})
    empty.validate_mapping([], TARGET_FIELDS)
    empty_plan = SyncPlanner().build_plan(source, [], empty)
    assert empty_plan.operations[0].fields == {"fld_id": "s1", "fld_deleted": False}


def test_update_includes_only_changed_business_field_and_repairs_identity_only_record():
    source = [{"_id": "s1", "_widget_pi": "PLA01"}]
    target = [{"record_id": "rec1", "fields": {"jdy_id": "s1", "jdy_deleted": False}}]
    plan = SyncPlanner().build_plan(source, target, approved_policy())
    assert plan.counts["UPDATE"] == 1
    assert plan.operations[0].fields == {"fld_pi": "PLA01"}
    assert plan.operations[0].action != "CREATE"


def test_second_run_is_skip_and_protected_fields_are_not_serialized():
    policy = approved_policy()
    source = [{"_id": "s1", "_widget_pi": "PLA01"}]
    target = [{"record_id": "rec1", "fields": {"jdy_id": "s1", "jdy_deleted": False, "PI Code": "PLA01", "Internal Notes": "protected"}}]
    plan = SyncPlanner().build_plan(source, target, policy)
    assert plan.counts["SKIP"] == 1
    assert serialize_feishu_fields(policy.build_update_fields(source[0]), TARGET_FIELDS) == {"PI Code": "PLA01"}
