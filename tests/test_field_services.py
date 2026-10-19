import pytest

from jdy_feishu_sync.services.field_discovery import compare_fields
from jdy_feishu_sync.services.field_ownership import FieldOwnershipError, FieldOwnershipPolicy, ManagedField


def test_exact_field_candidate_and_protected_default():
    result = compare_fields([{"name": "src", "label": " PI Code ", "type": "text"}], [{"field_id": "fld", "field_name": "PI Code", "type": 1}])
    assert result[0].status == "candidate"
    policy = FieldOwnershipPolicy([])
    assert policy.build_update_fields({"src": "PLA"}) == {}


def test_explicit_mapping_only_and_unknown_target_fails():
    policy = FieldOwnershipPolicy([ManagedField("src", "fld")])
    fields = [{"name": "src", "label": "PI Code", "type": "text"}]
    target = [{"field_id": "fld", "field_name": "PI Code", "type": 1}]
    policy.validate_mapping(fields, target)
    assert policy.build_update_fields({"src": "PLA", "other": "secret"}) == {"fld": "PLA"}
    with pytest.raises(FieldOwnershipError):
        FieldOwnershipPolicy([ManagedField("src", "missing")]).validate_mapping(fields, target)
