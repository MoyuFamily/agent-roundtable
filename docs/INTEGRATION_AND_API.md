# 接入方式与 API 参考

本文合并了原有的 Python API、Adapter 规范与各平台集成说明，作为开发集成与宿主接入的统一参考。

---

## 接入模式选型

| 模式 | 入口 | 适用场景 | 执行方式 |
|---|---|---|---|
| **Python 核心库** | `roundtable.RoundtableCore` | 嵌入 Python 应用或脚本，需要异常感知与完整控制 | 进程内调用，校验失败抛异常 |
| **Error-Safe Facade** | `roundtable.adapters.generic.Roundtable` | 生产宿主或非可信调用方，希望统一结构化错误 | 进程内调用，所有方法返回 `dict`（含 `{"error": "..."}`） |
| **Hermes Toolset** | `roundtable.adapters.hermes` | Hermes Agent 原生工具集（`toolsets: [roundtable]`） | 自动注册 12 个工具，飞书通知异步发送 |
| **MCP Server** | `python3 -m roundtable.mcp` | Claude Code、Cursor、Windsurf 等 MCP 客户端 | 支持 stdio（默认）与 HTTP/SSE（`--http`，默认 `8200`） |
| **HTTP Bridge** | `CodexBridge` / `GenericBridge` | Codex CLI、WorkBuddy 等通过 HTTP 驱动的宿主 | 暴露 REST 端点 + `/tool` 全工具分发，可配鉴权与 Webhook |
| **Agent Daemon** | `python3 -m roundtable.agent` | 需要常驻注册、心跳与自动接收 `summon`/`invitation` 的运行时 | 轮询 `inbox` 并确认召集/邀请；发言仍由宿主负责 |
| **调度器封装** | `ManagedOrchestrator` / `FederatedOrchestrator` | 简化同宿主建会或基于技能与在线状态的联邦召集 | 封装 `RoundtableCore` 与 `dispatch` 表状态管理 |

---

## Python 核心 API (`RoundtableCore` & `Roundtable`)

### 初始化

```python
from roundtable import RoundtableCore
from roundtable.adapters.generic import Roundtable
from roundtable.db import RoundtableDB

# 1. 标准核心库（db 默认按 ROUNDTABLE_DB -> ~/.roundtable/roundtable.db 解析）
core = RoundtableCore(db=RoundtableDB(), send_fn=None, on_event=None)

# 2. 错误安全 Facade（永不抛异常，出错返回 {"error": "..."}）
rt = Roundtable(db_path="/tmp/discussions.db", send_fn=None)
```

### 方法速查表

| `RoundtableCore` 方法 | `Roundtable` Facade | 关键参数与说明 |
|---|---|---|
| `create_discussion(...)`（别名 `init`） | `init(...)`（别名 `create_discussion`） | `topic, participants, *, context=None, max_rounds=5, speech_order="fixed", created_by="coordinator", output_path=None, notifications=None, status="active", web=True, web_port=8199, expires_at=None, template=None` |
| `speak(...)` | `speak(...)` | `discussion_id, participant, content, *, reply_to=None`；`round 0` 仅限 `"coordinator"` 开场 |
| `read(...)` | `read(...)` | `discussion_id, *, since_round=None, participant=None`；返回完整发言、`context_revision`、`evidence`、`materials`、`decision_report`、`context_history`、`conclusion` |
| `status(...)`（别名 `get_status`） | `get_status(...)`（别名 `status`） | `discussion_id`；返回 `next_speaker`、`dispatches`、`total_rounds`、`completed_rounds`、`current_round`、`convergence_score` |
| `update_context(...)` | `update_context(...)` | `discussion_id, context, *, source, expected_revision, reason=None, evidence=None`；原子修订简报与证据，不消耗轮次 |
| `add_material(...)` | `add_material(...)` | `discussion_id, material, *, source, expected_revision`；导入不可变材料包并合入 `evidence.sources` |
| `read_material(...)` | `read_material(...)` | `discussion_id, source_id, *, offset=0, limit=10, query=None`；按段分页读取完整材料原文 |
| `record_finding(...)` | — | `discussion_id, finding_type, content, related_speeches`；记录关联同场发言 ID 的 `consensus` / `disagreement` / `new_point` |
| `summarize(...)` | `summarize(...)` | `discussion_id, *, compact=False`；返回 `structured_summary`（含完整结论）；`compact=True` 省略 `rounds` 与 `formatted_history` |
| `end_discussion(...)`（别名 `end`） | `end(...)` | `discussion_id, *, force=False, conclusion=None, report=None, expected_revision=None`；`force=True` 取消会议；提交 `report` 时须传 `expected_revision` 且不可同时传 `conclusion`/`force` |
| `list_discussions(...)` | `list(...)`（别名 `list_discussions`） | `*, status=None, limit=50` |
| `advance(...)` | `advance(...)` | `discussion_id`；仅用于显式跳过当前轮，正常发言结束会自动推进 |
| `notify(...)` | `notify(...)` | `discussion_id, event, **kwargs`；手动触发 `round_start` / `speech` / `round_end` / `concluded` |
| `calculate_convergence(...)` | — | `discussion_id, round_num`；基于已记录 `findings` 计算比例，无标注时为 `None` |
| `run_demo(...)` | `run_demo(...)` | 运行内置演示讨论（不调用模型） |

> 语义提示：`total_rounds` 与 `completed_rounds` 统计实际参与者发言轮数（不含 `round 0` 开场和空轮），`current_round` 仅作引擎游标；`Roundtable.end_discussion` 别名仅透传 `force`/`conclusion`，提交 `report` 请使用 `rt.end(...)`。

---

## 数据模型与异常

### `roundtable.models`（纯 dataclass）

- `Discussion`: `id`, `topic`, `context`, `status`, `max_rounds`, `current_round`, `speech_order`, `created_by`, `created_at`, `concluded_at`, `conclusion`, `convergence_score`, `output_path`, `notifications`
- `Participant`: `discussion_id`, `participant`, `role`, `perspective`, `display_name`, `joined_at`, `is_active`
- `Speech`: `id`, `discussion_id`, `round`, `participant`, `content`, `reply_to`, `created_at`
- `Finding`: `id`, `discussion_id`, `type`, `content`, `round`, `related_speeches`
- `ConvergenceRecord`: `discussion_id`, `round`, `score`, `consensus_count`, `disagreement_count`, `new_point_count`

### `roundtable.exceptions`（全部继承自 `RoundtableError(ValueError)`）

`RoundtableError` · `DiscussionNotFoundError` · `DiscussionNotActiveError` · `InvalidParticipantError` · `InvalidSpeechOrderError` · `InvalidFindingTypeError` · `InvalidReplyToError`

> 说明：校验或环境错误可能直接抛出标准 `ValueError`；所有工具入口均使用同一底层 `RoundtableDB`（常见直接方法包括 `connect`、`create_discussion`、`get_discussion`、`list_discussions`、`add_speech`、`update_context`、`add_material`、`get_material`、`upsert_agent`、`create_dispatch`、`create_summon` 等，详见 `src/roundtable/db.py`）。

---

## MCP Server、HTTP Bridge 与 Agent Daemon

### 1. MCP Server（stdio / HTTP-SSE）

```bash
# 自动为 Claude Code / Cursor / Windsurf 写入 MCP 配置
python3 -m roundtable.skills.mcp-roundtable.install --platform=auto

# 手动启动 stdio 模式（默认）或 HTTP/SSE 模式（默认仅监听本机 127.0.0.1:8200）
python3 -m roundtable.mcp --db /path/to/shared.db
python3 -m roundtable.mcp --http --host 127.0.0.1 --port 8200 --db /path/to/shared.db
```

完整 27 个 MCP 工具、5 类资源 URI 与 3 个提示词见 [系统架构](architecture.md#mcp-server-层)。

### 2. HTTP Bridge (`CodexBridge` & `GenericBridge`)

```bash
# 启动内置 Codex Bridge（默认 http://127.0.0.1:8201）
python3 -m roundtable.codex --agent-id codex-local --port 8201 --db /path/to/shared.db --auth-token SECRET
```

Python 中也可以直接实例化 `roundtable.mcp.bridges.GenericBridge`（默认端口 `8202`）或 `CodexBridge`，支持 `port=0` 动态端口及可选 `webhook_url`。配置 `auth_token` 后，除 `GET /health` 外所有端点均校验 `Authorization: Bearer <token>` 或 `X-Roundtable-Token`：

| 端点 | 方法 | 用途 |
|---|---|---|
| `/health` | `GET` | 存活探测并刷新本地心跳时间戳 |
| `/agent` | `GET` | 返回当前注册的 Agent 元信息 |
| `/inbox` | `GET` | 读取未读收件箱消息（**兼容旧行为：读取即标记已读**；可靠消费请改用 `/tool` 调 `roundtable_inbox(mark_read=false)` + `roundtable_ack_inbox`） |
| `/status/<discussion_id>` | `GET` | 获取讨论状态（不存在返回 JSON `404`） |
| `/tool` | `POST` | `{"name": "<tool_name>", "arguments": {...}}`，分发全部 27 个 MCP 工具（含 `roundtable_add_material`、`roundtable_read_material`、`roundtable_get_prompt`） |
| `/speak` | `POST` | `roundtable_speak` 的快捷入口（共用同一处理器与下一位通知逻辑） |
| `/invite` / `/summon` | `POST` | 接收邀请/召集；仅当 `accept_policy == "auto"` 时自动加入并返回 `accepted: true` |
| `/turn` | `POST` | 将轮次提示转发至已配置的 `webhook_url` |

### 3. Agent Daemon & 调度器

```bash
python3 -m roundtable.agent --agent-id claude-1 --platform claude-code --skill agent-roundtable --accept-policy auto
```

Daemon 周期性刷新心跳、以 `mark_read=false` 仅过滤拉取 `summon` / `invitation` 消息，并在成功接受或拒绝后调用 `roundtable_ack_inbox`；发言 (`turn`) 始终留给宿主执行。同进程/跨进程程序化创建可使用 `roundtable.ManagedOrchestrator` 与 `roundtable.FederatedOrchestrator`。

---

## Hermes Agent 与通知集成

在 Hermes 配置中启用 `toolsets: [roundtable]` 后，模块会自动向 Hermes 注册 12 个工具：`roundtable_init`、`roundtable_speak`、`roundtable_read`、`roundtable_update_context`、`roundtable_add_material`、`roundtable_read_material`、`roundtable_status`、`roundtable_summarize`、`roundtable_end`、`roundtable_list`、`roundtable_advance`、`roundtable_notify`。

### 通知配置 (`notifications`)

```python
def my_send(platform: str, chat_id: str, message: str) -> None:
    print(f"[{platform}:{chat_id}] {message}")

rt = Roundtable(send_fn=my_send)
rt.init(
    topic="架构评审",
    participants=[...],
    notifications={
        "enabled": True,
        "channels": [{"platform": "feishu", "chat_id": "oc_xxx"}],
        "events": ["round_start", "speech", "round_end", "concluded"],
    },
)
```

- Hermes 适配器默认通过异步线程调用 `~/.hermes/scripts/feishu-send.py` 发送飞书通知。
- 如需直接推送 Discord / Slack Webhook，可使用 `roundtable.WebhookSender`（`send_discord` / `send_slack`）或在 `notifications["webhooks"]` 中配置。

---

## Web Viewer 与导出

- `create_discussion(..., web=True, web_port=8199, expires_at=None)` 默认尽力启动本地 Node.js 18+ Web Viewer，返回值包含 `web_status`（`ready` / `failed` / `disabled`）、`web_url`、`web_error`、`web_help`。
- **iframe 嵌入**：分享弹窗支持复制精简嵌入视图（`/embed/<token>`，无顶部导航、无导出按钮、支持 SSE 实时更新；密码保护讨论会提示在新标签页打开）。
- **导出**：Markdown 导出始终可用；PDF 导出采用请求级独立渲染进程，正文中的原始 HTML 与远程图片仅作纯文本处理。

---

## 自定义宿主 Adapter 接口 (`RoundtableAdapter`)

对于需要把不同框架包装成统一对象由宿主自行调度的场景，可继承 `roundtable.adapters.base.RoundtableAdapter` 或直接使用 `roundtable.adapters.simple.SimpleAdapter`：

```python
import roundtable
from roundtable.adapters.base import RoundtableAdapter
from roundtable.adapters.simple import SimpleAdapter

class CustomAdapter(RoundtableAdapter):
    def get_persona(self):
        return {"name": "Alice", "role": "engineer", "avatar": "👩‍💻", "title": "技术专家"}

    async def speak(self, context):
        return f"Topic: {context['topic']}"

    async def listen(self, speech):
        return None

roundtable.register_adapter("custom", CustomAdapter)
simple = SimpleAdapter(name="Bob", role="pm", speak_fn=lambda ctx: f"Round {ctx['round']}: ...")
```

- `roundtable.list_adapters()` / `roundtable.get_adapter(name)` 查询已注册适配器。
- **宿主职责**：当前 `RoundtableCore` 不会自动运行已注册的 Adapter；宿主需自行调度 `get_persona()`、`speak()`、`listen()`、控制超时与失败重试，并将发言通过 `RoundtableCore.speak()` 或工具写入。

---

## 环境变量速查

| 变量名 | 默认值 | 用途 |
|---|---|---|
| `ROUNDTABLE_DB` | `~/.roundtable/roundtable.db` | 默认 SQLite 数据库路径 |
| `PUPPETEER_EXECUTABLE_PATH` | Puppeteer 内置探测路径 | 指定用于 PDF 导出的本地 Chrome / Chromium 可执行文件路径 |
| `ROUNDTABLE_PDF_TIMEOUT_MS` | `60000`（上限 `120000`） | 单次 PDF 渲染超时时间（毫秒） |
| `ROUNDTABLE_PDF_NO_SANDBOX` | 未设置（开启沙箱） | 设为 `1` 时向浏览器传 `--no-sandbox`（仅限受控 CI 容器使用） |
| `ROUNDTABLE_REQUIRE_PDF` | 未设置 | 测试中设为 `1` 时，缺少浏览器直接失败而非跳过 |
| `HERMES_PROFILE` | `default` | Hermes 适配器发送飞书通知时使用的 Profile 名 |
