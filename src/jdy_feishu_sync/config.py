from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


class ConfigError(ValueError):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    api_key: str
    app_id: str
    entry_id: str
    base_url: str = "https://api.jiandaoyun.com/api/v5"
    timeout_seconds: float = 20.0

    @classmethod
    def from_env(cls, env_file: str | Path | None = None) -> "Settings":
        # The CLI is normally started from the project root. Keep explicit
        # paths supported, while making the documented `.env` workflow work
        # when no path is supplied.
        load_dotenv(env_file or Path.cwd() / ".env", override=False)
        required = {name: os.getenv(name, "").strip() for name in ("JDY_API_KEY", "JDY_APP_ID", "JDY_ENTRY_ID")}
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ConfigError("Missing required configuration: " + ", ".join(missing))
        try:
            timeout = float(os.getenv("JDY_TIMEOUT_SECONDS", "20"))
        except ValueError as exc:
            raise ConfigError("JDY_TIMEOUT_SECONDS must be a number") from exc
        if timeout <= 0:
            raise ConfigError("JDY_TIMEOUT_SECONDS must be greater than zero")
        return cls(
            api_key=required["JDY_API_KEY"],
            app_id=required["JDY_APP_ID"],
            entry_id=required["JDY_ENTRY_ID"],
            base_url=os.getenv("JDY_BASE_URL", cls.base_url).rstrip("/"),
            timeout_seconds=timeout,
        )


@dataclass(frozen=True)
class FeishuSettings:
    app_id: str
    app_secret: str
    app_token: str
    table_id: str
    base_url: str = "https://open.feishu.cn/open-apis"
    auth_url: str = "https://accounts.feishu.cn/oauth/v3/token"
    timeout_seconds: float = 20.0

    @classmethod
    def from_env(cls, env_file: str | Path | None = None) -> "FeishuSettings":
        load_dotenv(env_file or Path.cwd() / ".env", override=False)
        names = ("FEISHU_APP_ID", "FEISHU_APP_SECRET", "FEISHU_APP_TOKEN", "FEISHU_TABLE_ID")
        values = {name: os.getenv(name, "").strip() for name in names}
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise ConfigError("Missing required configuration: " + ", ".join(missing))
        try:
            timeout = float(os.getenv("FEISHU_TIMEOUT_SECONDS", os.getenv("JDY_TIMEOUT_SECONDS", "20")))
        except ValueError as exc:
            raise ConfigError("FEISHU_TIMEOUT_SECONDS must be a number") from exc
        if timeout <= 0:
            raise ConfigError("FEISHU_TIMEOUT_SECONDS must be greater than zero")
        return cls(
            app_id=values["FEISHU_APP_ID"],
            app_secret=values["FEISHU_APP_SECRET"],
            app_token=values["FEISHU_APP_TOKEN"],
            table_id=values["FEISHU_TABLE_ID"],
            base_url=os.getenv("FEISHU_BASE_URL", cls.base_url).rstrip("/"),
            auth_url=os.getenv("FEISHU_AUTH_URL", cls.auth_url).rstrip("/"),
            timeout_seconds=timeout,
        )
