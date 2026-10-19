from jdy_feishu_sync.services.schema_mapping import build_proposals, validate_proposals


def test_exact_compatible_match_and_missing_field_proposal():
    proposals = build_proposals(
        [{"name": "src_text", "label": "PI Code", "type": "text"}, {"name": "src_upload", "label": "Attachment", "type": "upload"}],
        [{"field_id": "fld_pi", "field_name": "PI Code", "type": 1}],
    )
    assert proposals[0].action == "MATCH_EXISTING"
    assert proposals[0].confidence == "HIGH"
    assert proposals[0].target_id == "fld_pi"
    assert proposals[1].action == "UNSUPPORTED"


def test_missing_compatible_field_is_unapproved_create_new():
    proposal = build_proposals([{"name": "src", "label": "New Field", "type": "text"}], [])[0]
    assert proposal.action == "CREATE_NEW"
    assert proposal.approved is False
    assert validate_proposals([proposal]) == []


def test_same_name_incompatible_field_is_ambiguous():
    proposal = build_proposals([{"name": "src", "label": "Amount", "type": "number"}], [{"field_id": "fld", "field_name": "Amount", "type": 1}])[0]
    assert proposal.action == "AMBIGUOUS"
    assert proposal.approved is False


def test_duplicate_existing_name_is_ambiguous():
    proposal = build_proposals([{"name": "src", "label": "Name", "type": "text"}], [{"field_id": "a", "field_name": "Name", "type": 1}, {"field_id": "b", "field_name": "Name", "type": 1}])[0]
    assert proposal.action == "AMBIGUOUS"
