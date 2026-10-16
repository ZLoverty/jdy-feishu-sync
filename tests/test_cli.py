from jdy_feishu_sync.cli import main


def test_parser_rejects_missing_configuration(monkeypatch, capsys, tmp_path):
    for key in ("JDY_API_KEY", "JDY_APP_ID", "JDY_ENTRY_ID"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
    assert main(["check"]) == 1
    assert "Missing required configuration" in capsys.readouterr().err
