# jdy-feishu-sync

P0 provides a read-only Jiandaoyun API client and diagnostic CLI. No Feishu writes, webhooks, SQLite, or synchronization logic are included yet.

## Install

```bash
python -m pip install -e ".[test]"
copy .env.example .env
```

Fill `.env` with `JDY_API_KEY`, `JDY_APP_ID`, and `JDY_ENTRY_ID`. Existing environment variables take precedence over `.env`.

## Commands

```bash
jdy-sync check
jdy-sync inspect-fields
jdy-sync inspect-records --limit 5
jdy-sync count-records
jdy-sync verify
```

Commands print metadata only; they do not print complete business records or credentials. `verify` performs the P0 read-only checks, including complete cursor-based record traversal.

## P0 boundaries

The Jiandaoyun API is the read-only source used by this phase. API keys are never logged. Network, HTTP, JSON, platform, authentication, and pagination failures are surfaced as errors; partial pagination results are not reported as successful.

Run automated tests with `pytest`. Tests use mocked HTTP responses and never require a real account or network.
