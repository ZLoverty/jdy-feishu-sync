import pytest

from jdy_feishu_sync.config import ConfigError, Settings


def test_loads_configuration(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("JDY_API_KEY=file-key\nJDY_APP_ID=app\nJDY_ENTRY_ID=entry\n", encoding="utf-8")
    for key in ("JDY_API_KEY", "JDY_APP_ID", "JDY_ENTRY_ID"):
        monkeypatch.delenv(key, raising=False)
    settings = Settings.from_env(env_file)
    assert settings.api_key == "file-key"
    assert settings.entry_id == "entry"


def test_missing_key_is_clear(monkeypatch, tmp_path):
    monkeypatch.delenv("JDY_API_KEY", raising=False)
    monkeypatch.setenv("JDY_APP_ID", "app")
    monkeypatch.setenv("JDY_ENTRY_ID", "entry")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigError, match="JDY_API_KEY"):
        Settings.from_env()


def test_default_env_file_is_loaded(monkeypatch, tmp_path):
    for key in ("JDY_API_KEY", "JDY_APP_ID", "JDY_ENTRY_ID"):
        monkeypatch.delenv(key, raising=False)
    (tmp_path / ".env").write_text(
        "JDY_API_KEY=default-key\nJDY_APP_ID=default-app\nJDY_ENTRY_ID=default-entry\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    settings = Settings.from_env()
    assert settings.api_key == "default-key"
    assert settings.app_id == "default-app"
