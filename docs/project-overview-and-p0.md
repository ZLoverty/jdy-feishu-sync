# Agent Instruction — Jdy Feishu Sync

## Project Overview

项目名称：`jdy-feishu-sync`

目标：开发一个轻量级、可靠的 Python 服务，将简道云表单数据单向同步至飞书多维表格，同时严格保护飞书独立维护的字段。

本项目采用分阶段开发，每个阶段必须独立验收。当前仅实施 **P0 — Project Bootstrap & Jiandaoyun Read-Only Integration**。

**禁止提前实现 P1–P5。**

---

# Part A — Global Project Specification

## A1. 核心需求

### 数据同步

- 简道云是同步字段的 Source of Truth。
- 飞书多维表格是同步目标。
- 支持新增、修改和软删除。
- 目标是接近实时同步。
- 数据规模小于 1,000 条。
- 通过简道云记录 `_id` 唯一识别来源记录。
- 同一来源记录不得在飞书创建重复记录。

### 字段所有权

这是本项目最高优先级的数据安全约束。

飞书中的字段分为两类：

1. **Managed Fields**：由简道云同步服务管理。
2. **Protected Fields**：由飞书用户或其他飞书流程独立维护。

同步服务必须满足：

- 只允许写入显式配置的 Managed Fields。
- 不得修改 Protected Fields。
- 不得根据同名字段自动扩大同步范围。
- 不得使用整行覆盖方式更新飞书记录。
- 不得通过删除飞书整行来响应简道云删除事件。
- 所有写入路径，包括初始化、增量同步、重试、对账，都必须经过统一的字段白名单校验。
- 新增飞书字段默认属于 Protected Fields，除非管理员明确加入白名单。

### 记录删除

当简道云记录被删除：

- 不删除对应的飞书记录。
- 只更新同步系统管理的软删除状态。
- 保留所有飞书人工字段。
- 如果相同来源 `_id` 恢复，则恢复原飞书记录。
- 如果创建了不同 `_id` 的新记录，即使业务内容相同，也视为新记录。

### 可靠性

- 同步操作必须尽可能幂等。
- 需要处理 API 超时、限流和暂时性失败。
- Webhook 重复或乱序不得造成数据错误。
- Worker 重启不得丢失已接收但尚未处理的任务。
- 定时对账应能修复漏同步。
- 对账来源读取不完整时，禁止执行删除操作。

## A2. 技术约束

使用：

- Python 3.11+
- `httpx`
- `python-dotenv`
- `PyYAML`（后续字段映射使用）
- `pytest`
- SQLite（后续阶段持久化同步状态）
- FastAPI（后续 Webhook 阶段）
- systemd（生产部署）

原则：

- 不引入 MySQL、PostgreSQL、Redis 或消息队列。
- 不引入复杂微服务架构。
- API Adapter 与业务同步逻辑分离。
- 使用类型标注。
- 使用结构化日志。
- 所有凭证通过环境变量配置。
- 不在代码中硬编码密钥。
- 不把真实业务数据作为测试 fixture 提交仓库。
- 不使用未经确认的 API 字段结构。
- 对未确认的 API 行为进行文档核实或实测，不得凭猜测实现。

## A3. 阶段规划

| Phase | Scope |
|---|---|
| P0 | 项目初始化、简道云 API 接入、只读验证 |
| P1 | 飞书 API 接入、字段元数据、字段所有权配置 |
| P2 | 初始化同步、字段级 Upsert、幂等 |
| P3 | Webhook 实时同步、持久化任务与重试 |
| P4 | 定时对账、软删除、自恢复 |
| P5 | 生产部署、日志、监控、备份 |

当前仅实施 P0。

---

# Part B — P0 Implementation

## P0.1 目标

建立正式的简道云只读 API Client，并将已经验证过的 API 行为固化为自动化测试和文档。

P0 必须支持：

1. 从 `.env` 加载配置。
2. 验证简道云 API 连接。
3. 获取指定应用的表单列表。
4. 验证目标表单存在。
5. 获取目标表单的字段元数据。
6. 读取目标表单的记录。
7. 分页读取全部记录。
8. 输出安全的诊断信息。
9. 处理 API 和网络错误。
10. 提供不依赖真实账号的自动化测试。

P0 只能执行只读 API 请求。

## P0.2 已验证的简道云 API 行为

以下信息已经通过人工测试验证，Agent 应直接将其作为实现依据。

### API Base URL

```text
https://api.jiandaoyun.com/api/v5
```

### Authentication

使用 API Key：

```http
Authorization: Bearer <JDY_API_KEY>
Content-Type: application/json
```

API Key 由环境变量提供。

### 获取表单列表

```http
POST /app/entry/list
```

请求：

```json
{
  "app_id": "<JDY_APP_ID>"
}
```

已验证：

- HTTP 200。
- 返回 JSON 包含 `forms`。
- 每个表单包含 `name` 和 `entry_id`。
- 已成功列出目标应用下的多个表单。

### 获取表单字段定义

```http
POST /app/entry/widget/list
```

请求：

```json
{
  "app_id": "<JDY_APP_ID>",
  "entry_id": "<JDY_ENTRY_ID>"
}
```

已验证字段结构：

```json
{
  "name": "_widget_1730273046580",
  "widgetName": "_widget_1730273046580",
  "label": "PI Code",
  "type": "text"
}
```

字段含义：

- `name`：稳定的字段内部 ID。
- `widgetName`：当前观察到与 `name` 相同。
- `label`：用户看到的字段名称。
- `type`：字段类型。

**重要：不要把 `widgetName` 当作显示名称。显示名称应使用 `label`。**

当前测试表单返回 25 个字段，包含：

- `text`
- `textarea`
- `datetime`
- `combo`
- `radiogroup`
- `user`
- `subform`
- `upload`

P0 只负责读取和保留字段类型，不实现飞书侧的类型转换。

### 获取表单记录

```http
POST /app/entry/data/list
```

请求：

```json
{
  "app_id": "<JDY_APP_ID>",
  "entry_id": "<JDY_ENTRY_ID>",
  "limit": 2
}
```

已验证：

- HTTP 200。
- 响应包含 `data` 记录数组。
- 记录包含 `_id`。
- 普通业务字段以 `_widget_...` 形式存储。
- 记录还包含 `creator`、`updater`、`createTime`、`updateTime`、`appId`、`entryId` 等元数据。

示例记录 ID：

```text
6721e4298c27782a4080a906
```

该 ID 仅作为格式示例，不得硬编码到应用逻辑。

### 分页

实现全量读取时：

- 遵守官方接口的单页记录数量限制。
- 按官方文档规定的 `data_id` 游标方式分页。
- 不得使用未经确认的 offset 分页。
- 不得假设一次请求可以返回全部数据。
- 必须检测游标未前进、重复记录以及异常终止。
- 分页失败时必须抛出异常，不得返回看似完整的部分数据。
- 空表必须正确返回空列表。

参考官方文档：

https://hc.jiandaoyun.com/open/

## P0.3 环境变量

项目根目录创建 `.env.example`：

```dotenv
JDY_API_KEY=
JDY_APP_ID=
JDY_ENTRY_ID=
JDY_BASE_URL=https://api.jiandaoyun.com/api/v5
JDY_TIMEOUT_SECONDS=20
```

使用 `python-dotenv` 加载 `.env`。

正式变量名统一使用 `JDY_ENTRY_ID`，不再使用容易混淆的 `JDY_FORM_ID`。

要求：

- 缺少必要配置时给出清晰错误。
- 不得在日志中打印 API Key。
- 不得将 `.env` 提交 Git。
- `.env.example` 可以提交，但不得包含真实凭证。
- 默认不覆盖操作系统已有环境变量。

## P0.4 项目结构

建立：

```text
jdy-feishu-sync/
├── pyproject.toml
├── README.md
├── .gitignore
├── .env.example
├── docs/
│   ├── architecture.md
│   └── p0-verification.md
├── src/
│   └── jdy_feishu_sync/
│       ├── __init__.py
│       ├── cli.py
│       ├── config.py
│       ├── models.py
│       └── adapters/
│           ├── __init__.py
│           └── jiandaoyun.py
└── tests/
    ├── test_config.py
    ├── test_jiandaoyun.py
    └── test_cli.py
```

不创建尚未使用的飞书客户端、SQLite 数据库或 Webhook 服务。

## P0.5 Jiandaoyun Client

在 `adapters/jiandaoyun.py` 实现可复用的 Client。

建议接口：

```python
class JiandaoyunClient:
    def list_entries(self) -> list:
        ...

    def get_widgets(self, entry_id: str) -> list:
        ...

    def list_records(
        self,
        entry_id: str,
        limit: int = 100,
    ) -> list:
        ...

    def iter_all_records(self, entry_id: str):
        ...
```

要求：

- 复用 HTTP Client 连接。
- 支持明确的请求超时。
- 对网络错误和平台业务错误进行区分。
- 对 HTTP 429 和临时性 5xx 实施有界重试。
- 使用指数退避。
- 不重试确定性的鉴权错误。
- 对响应结构进行必要验证。
- 使用异常而不是 `print` 报告 API 失败。
- 不允许读取失败后静默返回空列表。
- 所有 HTTP 调用集中在 Adapter 中。

字段和记录的数据结构应保留原始信息，避免过早转换导致数据丢失。

## P0.6 CLI

实现以下命令：

```bash
jdy-sync check
```

检查：

- 配置是否完整。
- API 是否可访问。
- 目标应用是否有权限。
- 目标表单是否存在。

```bash
jdy-sync inspect-fields
```

输出：

```text
Label       Field ID                   Type
PI Code     _widget_1730273046580     text
...
```

```bash
jdy-sync inspect-records --limit 5
```

默认只输出：

- 记录 ID。
- 字段 ID 列表。
- 记录数量。

不得默认打印完整业务数据。

```bash
jdy-sync count-records
```

通过完整分页统计记录数量。

```bash
jdy-sync verify
```

执行 P0 综合验证：

- 鉴权成功。
- 目标表单存在。
- 字段定义可读取。
- 记录接口可读取。
- 分页读取完整。

空表属于合法情况，不能因为记录数为零而报错。

## P0.7 Automated Tests

使用 pytest 和模拟 HTTP 响应。

至少覆盖：

1. `.env` 正常加载。
2. 缺少 API Key。
3. 获取表单列表成功。
4. 目标表单不存在。
5. 字段名称正确使用 `label`。
6. 字段类型正确解析。
7. 读取记录成功。
8. 空表。
9. 多页数据读取。
10. API 返回重复记录。
11. 分页游标未前进。
12. HTTP 401 / 403。
13. HTTP 429。
14. HTTP 500。
15. 网络超时。
16. JSON 格式错误。
17. API 业务错误。
18. 日志不包含 API Key。
19. CLI 正常退出。
20. CLI 出错时返回非零退出码。

测试不得依赖真实的简道云账号或网络。

可以额外提供手动集成测试，但必须显式启用，不能成为默认 pytest 测试的一部分。

## P0.8 Documentation

### README.md

说明：

- 项目目标。
- 字段所有权原则。
- 环境安装。
- `.env` 配置。
- CLI 使用方法。
- P0 当前功能。
- 尚未实现的功能。

### docs/architecture.md

记录：

- 简道云作为 Source of Truth。
- 飞书字段所有权隔离。
- 未来同步架构。
- 记录 ID 匹配原则。
- 软删除原则。
- 不使用整行覆盖。
- 各阶段职责边界。

### docs/p0-verification.md

记录：

- 已验证的 API Endpoint。
- 请求参数。
- 返回数据结构。
- 字段 ID 与 `label` 的区别