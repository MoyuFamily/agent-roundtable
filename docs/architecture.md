# Roundtable 系统架构

> 当前产品定位与路线图见 [产品方向](product/DIRECTION.md)。本页描述已有记录、接入与展示基础设施；角色选择、Agent 执行、模型配置和专业综合由宿主及协调者负责。

## 系统总览

```text
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          Multi-Agent Roundtable System                          │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌──────────┐  ┌────────┐  │
│  │ Claude Code │  │   Cursor    │  │  Windsurf   │  │ WorkBuddy│  │  Codex │  │
│  │  (stdio)    │  │  (stdio)    │  │  (stdio)    │  │ (HTTP)   │  │ (HTTP) │  │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └────┬─────┘  └───┬────┘  │
│         │                │                │               │            │        │
│         └────────────────┼────────────────┘               └─────┬──────┘        │
│                          │ MCP Protocol (stdio / SSE)           │ HTTP Bridge   │
│                          ▼                                      ▼               │
│  ┌───────────────────────────────────────────────────────────────────────────┐  │
│  │                      MCP & Bridge Layer (roundtable.mcp)                  │  │
│  │   Tools (27) │ Static Resources (2) + Templates (3) │ Prompts (3)         │  │
│  └───────────────────────────────────┬───────────────────────────────────────┘  │
│                                      │                                          │
│                                      ▼                                          │
│  ┌───────────────────────────────────────────────────────────────────────────┐  │
│  │                     roundtable (Core Python Package)                      │  │
│  │                                                                           │  │
│  │  core.py ─── db.py ─── schema.py (v7) ─── evidence.py ─── materials.py   │  │
│  │     │                                                                     │  │
│  │     ├── shared DB watcher (data_version) ──► MCP resource notifications   │  │
│  │     ├── web_sync.py / web_publisher.py   ──► Web Viewer (Node / builtin) │  │
│  │     └── notify.py / webhook.py           ──► Platform push                │  │
│  │                                                                           │  │
│  │  SQLite (WAL) ─ discussions │ context_revisions │ materials │ reports ... │  │
│  └───────────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

## 核心模块分布

```text
src/roundtable/
├── __init__.py          # 公共导出与适配器注册表
├── core.py              # RoundtableCore 业务逻辑、轮次推进与报告一致性协调
├── db.py                # SQLite 存储层（WAL 模式、事务校验与 CRUD）
├── schema.py            # Schema v7 DDL 与增量迁移 (_MIGRATIONS)
├── models.py            # 纯 dataclass 模型与实际评审轮次计算 (review_round_counts)
├── evidence.py          # 结构化证据 (EVIDENCE_SCHEMA) 与决策报告 (REPORT_SCHEMA) 校验/渲染
├── materials.py         # 材料包契约 (MATERIAL_SCHEMA)、TXT/MD/CSV/PDF 分段读取与检索
├── import_material.py   # CLI 入口：python -m roundtable.import_material
├── output.py            # 统一摘要 Markdown 构建与文件输出
├── formatter.py         # 终端/文本格式化辅助
├── template.py          # 内置 7 个 JSON 模板加载与填充
├── orchestrator.py      # ManagedOrchestrator / FederatedOrchestrator 调度封装
├── agent.py             # AgentDaemon 常驻心跳与 summon/invitation 消费者
├── codex.py             # Codex HTTP Bridge CLI 入口
├── notify.py / webhook.py # 平台消息回调与 Discord / Slack Webhook
├── file_io.py           # 跨平台文件锁 (flock/msvcrt)、UTF-8 原子写入与 JSONL 追加
├── web_publisher.py / web_helpers.py / web_sync.py # Web Viewer 发布、并发同步与状态维护
├── exceptions.py        # RoundtableError 异常层级
├── adapters/            # base.py, simple.py, generic.py (Roundtable), hermes.py
├── mcp/                 # __main__.py, server.py, tools.py, resources.py, prompts.py, bridges/
├── skills/mcp-roundtable/ # 包内 MCP Skill 与平台配置自动安装脚本
└── web/                 # Express server.mjs, pdf-worker.mjs, viewer.js, embed.html 等
```

## 核心状态机

```text
                    ┌───────────────┐
                    │ 创建讨论      │
                    │ create_disc() │
                    └──────┬────────┘
                           │
           status='assembling'（可先导入材料 / 召集 Agent）
                           │
                           ▼
                    ┌───────────────┐
           ┌───────│    active     │◄──────────┐
           │       │ current_round │           │
           │       └──────┬────────┘           │
           │              │                    │
           │              ▼                    │
           │       ┌──────────────┐            │
           │       │  speak()     │            │
           │       │  add_speech  │            │
           │       └──────┬───────┘            │
           │              │                    │
           │      ┌───────┴────────┐           │
           │      │                │           │
           │      ▼                ▼           │
           │  round_complete   round_start     │
           │  (all spoke)     (1st speech)     │
           │      │                            │
           │      ▼                            │
           │  new_round > max?                 │
           │   ├─ No  ─────────────────────────┘
           │   │  (auto advance)
           │   │
           │   ▼ Yes
           │  ┌───────────────┐
           │  │ auto_conclude │
           │  └──────┬────────┘
           │         │
           ▼         ▼
    ┌──────────┐  ┌──────────────┐
    │ cancelled│  │   concluded  │（仍可提交/修订 conclusion 或 report）
    │ (force)  │  │  (normal)    │
    └──────────┘  └──────────────┘
```

## 数据流与持久化

```text
  User/Agent                Core                   DB (SQLite)
     │                      │                        │
     │── create_disc() ────►│── INSERT disc ────────►│
     │◄── {disc_id} ────────│◄── {Discussion} ───────│
     │                      │                        │
     │── add_material() ───►│── validate packet ────►│ (materials + context_revisions)
     │── update_context() ─►│── check expected_rev ─►│ (context_revisions + evidence)
     │                      │                        │
     │── speak(id,who,txt)─►│── validate ───────────►│
     │                      │── INSERT speech ──────►│
     │                      │── check round_complete │
     │                      │── DB commit/watch ────►│ ──► MCP resource_updated
     │◄── {speech_id,round}─│                        │
     │                      │                        │
     │── end_disc(report) ─►│── validate refs/rev ──►│ (decision_reports + conclusion)
     │                      │── sync viewer & export │
     │                      │── Notifier ───────────►│ ──► send_fn / Webhook
```

## MCP Server 层

`roundtable.mcp` 将 Tool、Resource、Prompt 规格定义与可选 `mcp` SDK 解耦（纯 dict 声明，方便无依赖测试），并通过 `server.py` 暴露为标准 MCP Server：

- **`__main__.py`**：`python3 -m roundtable.mcp` 启动 stdio（默认），加 `--http --host 127.0.0.1 --port 8200` 启动 HTTP/SSE。
- **`server.py`**：初始化时声明 `resources.subscribe`，每个会话使用独立 SQLite 连接按约 `200ms` 检查 `PRAGMA data_version` 推送资源失效通知。
- **`bridges/`**：`GenericBridge`（默认 `8202`）与 `CodexBridge`（默认 `8201`）共用 HTTP 实现。

### MCP Tools（共 27 个）

| 类别 | Tool | 用途 |
|---|---|---|
| **Agent** | `roundtable_register_agent` | 注册 Agent、transport、skills 与可用性 |
| **Agent** | `roundtable_list_agents` | 按在线状态、skill、availability 查询 Agent |
| **Agent** | `roundtable_heartbeat` | 运行时心跳，刷新 `last_seen` 与 `availability` |
| **Dispatch** | `roundtable_summon_agents` | 创建或使用 `assembling` 会议并召集 Agent |
| **Dispatch** | `roundtable_dispatch_status` | 查询 dispatch / summon / readiness 状态并触发超时结算 |
| **Dispatch** | `roundtable_retry_summon` | 重投递 pending / delivered / failed / timeout summon |
| **Summon** | `roundtable_accept_summon` | 接受召集并原子加入参与者 |
| **Summon** | `roundtable_decline_summon` | 拒绝召集 |
| **Discussion** | `roundtable_create` | 创建讨论（支持 `status="assembling"` 与可选传统邀请） |
| **Discussion** | `roundtable_list` | 列出讨论，支持按状态过滤 |
| **Invitation** | `roundtable_invite` | 传统邀请 Agent 加入 |
| **Invitation** | `roundtable_accept_invite` | 接受传统邀请并加入参与者 |
| **Invitation** | `roundtable_decline_invite` | 拒绝传统邀请 |
| **Inbox** | `roundtable_inbox` | 读取消息（支持 `mark_read=false` 与 `message_types` 过滤） |
| **Inbox** | `roundtable_ack_inbox` | 按 `agent_id` 幂等确认已处理的消息 ID |
| **Context** | `roundtable_update_context` | 完整简报修订、结构化 `evidence`、乐观锁校验与历史保留 |
| **Materials** | `roundtable_add_material` | 导入不可变 JSON 材料包并登记 `evidence.sources`（不耗轮次） |
| **Materials** | `roundtable_read_material` | 按 `offset` / `limit` / 字面子串 `query` 分页读取完整材料片段 |
| **Speech** | `roundtable_speak` | 记录发言（协调者 `round 0` 开场与参与者逐轮发言） |
| **Speech** | `roundtable_read` | 读取发言、当前简报、历史版本、材料目录与结论 |
| **Speech** | `roundtable_wait_for_turn` | 轮询检查是否轮到自己发言（上限 `wait_seconds` 30s） |
| **Round** | `roundtable_advance` | 显式跳过当前轮次 |
| **Round** | `roundtable_status` | 获取状态、轮次统计、`next_speaker`、材料目录与 dispatch 状态 |
| **Findings** | `roundtable_record_finding` | 记录关联同场发言 ID 的 `consensus` / `disagreement` / `new_point` |
| **Conclude** | `roundtable_summarize` | 获取格式化摘要（包含完整结论，不自动包含原始材料正文） |
| **Conclude** | `roundtable_end` | 提交自由文本 `conclusion` 或校验版本的 `report`，或 `force=true` 取消 |
| **Prompts** | `roundtable_get_prompt` | 通过工具或 HTTP `/tool` 获取与 MCP Prompts 一致的阶段提示词 |

### MCP Resources & Prompts

- **静态资源（2 个）**：`roundtable://agents`（已注册 Agent）、`roundtable://discussions`（讨论列表）
- **模板资源（3 个）**：`roundtable://discussions/{id}`（讨论状态）、`roundtable://discussions/{id}/transcript`（完整 Markdown 记录）、`roundtable://invitations/{agent_id}`（待处理邀请）
- **提示词（3 个）**：`coordinator_kickoff`、`participant_turn`（按 `phase` 区分 `independent` 与 `response`）、`coordinator_summarize`

## 多 Agent 召集流程（主路径）

```text
  Coordinator              MCP Server                Registry/DB              Agent Bridge
       │                       │                         │                         │
       │── roundtable_summon_agents ────────────────────►│                         │
       │   topic / required_skill / min_accepts           │                         │
       │                       │── create discussion      │                         │
       │                       │   status='assembling' ──►│                         │
       │                       │── select online agents ─►│                         │
       │                       │── INSERT dispatch/summons│                         │
       │                       │── push_inbox(summon) ───►│                         │
       │                       │── POST /summon ──────────────────────────────────►│
       │                       │◄──────── roundtable_accept_summon ────────────────│
       │                       │── INSERT participant ───►│                         │
       │                       │── readiness met ─► active│                         │
       │◄── dispatch / readiness / summons ──────────────│                         │
```

`start_policy` 支持 `immediate`、`quorum`、`all`、`timeout`；满足条件后会议由 `assembling` 激活为 `active`。`roundtable_retry_summon` 复用既有 summon 行重投递；`allow_terminal_retry` 可在终态 dispatch 上释放旧 `idempotency_key` 后新建 dispatch。

## 多 Agent 邀请流程（传统路径）

```text
  Coordinator              MCP Server                Inbox/DB              Participant
       │                       │                        │                      │
       │── roundtable_create ─►│                        │                      │
       │   (+invite_agents)    │── INSERT discussion ──►│                      │
       │                       │── INSERT invitation ──►│                      │
       │                       │── push_inbox(invite) ─►│                      │
       │◄── {discussion_id} ───│                        │                      │
       │                       │                        │◄── roundtable_inbox ─│
       │                       │                        │── messages[] ───────►│
       │                       │◄────────── roundtable_accept_invite ──────────│
       │                       │── respond_invitation ─►│                      │
       │                       │── INSERT participant ─►│                      │
       │                       │── {accepted: true} ──────────────────────────►│
       │                       │◄────────────── roundtable_speak ──────────────│
       │                       │── INSERT speech ──────►│                      │
       │                       │   (push turn notice + DB watch resource_updated)
```

## Bridge 与调度模式

- **Bridge 设计**：`GenericBridge` 与 `CodexBridge` 共享 HTTP 请求处理器与 `AgentBridge.start/stop` 生命周期；`accept_policy=auto` 时自动接受邀请/召集，否则保持待处理；先绑定端口再登记端点，失败自动释放监听。HTTP Bridge 不运行模型，仅同步状态与转发可选 Webhook。
- **调度模式**：`ManagedOrchestrator` 用于同平台直接建会（`mode="managed"`）；`FederatedOrchestrator` 用于跨平台按技能、可用性与心跳召集（`mode="federated"`）。两者共享同一套状态表。

## 数据库 Schema (v7)

```text
discussions ──┬─► participants
              ├─► context_revisions (v5, +evidence v6)
              ├─► materials (v7)
              ├─► decision_reports (v6)
              ├─► speeches ──► findings
              ├─► convergence_history
              ├─► invitations ◄─── agents
              └─► dispatches ──► summons ──► summon_events
                                      ▲
                                      │
                                  agent_inbox
```

| 表 | 关键字段 | 说明 |
|---|---|---|
| `discussions` | `id`, `topic`, `status`, `current_round`, `max_rounds`, `conclusion` | 会议主表；`status` 含 `assembling/active/concluded/cancelled` |
| `participants` | `discussion_id + participant (PK)`, `role`, `perspective` | 初始传入或接受 invite/summon 后加入 |
| `speeches` | `id`, `discussion_id`, `round`, `participant`, `content` | 逐轮发言记录 |
| `findings` | `type (consensus/disagreement/new_point)`, `related_speeches` | 关联同场发言 ID 的显式观点标注 |
| `convergence_history` | `discussion_id + round (PK)`, `score` | 基于标注计算的轮次比例历史 |
| `agents` | `agent_id (PK)`, `platform`, `transport`, `endpoint`, `metadata` | 已注册 Agent（`metadata` 含 `skills` 与 `availability`） |
| `agent_inbox` | `id`, `agent_id`, `type`, `payload`, `read_at` | `summon` / `invitation` / `turn` 消息队列 |
| `invitations` | `discussion_id + agent_id (UNIQUE)`, `status` | 传统邀请记录 |
| `dispatches` | `id`, `discussion_id`, `mode`, `start_policy`, `status` | 召集调度批次（v3，v4 补索引） |
| `summons` | `id`, `dispatch_id`, `agent_id`, `status`, `expires_at` | 单 Agent 召集生命周期（v3，v4 补索引） |
| `summon_events` | `summon_id`, `dispatch_id`, `event`, `payload` | 召集审计事件流 |
| `context_revisions` | `discussion_id + revision (PK)`, `context`, `evidence`, `source` | 简报历史（v5 新增，v6 增 `evidence` 列；首次修订自动保留 v0） |
| `decision_reports` | `discussion_id (PK)`, `context_revision`, `report` | 结构化决策报告 JSON（v6） |
| `materials` | `discussion_id + source_id (PK)`, `material`, `created_at` | 不可变材料包原文与分段状态（v7） |

## 部署形态与可靠性

| 形态 | 启动方式 | 适用场景 |
|---|---|---|
| **stdio MCP** | `python3 -m roundtable.mcp` | 单机本地编辑器（Claude Code / Cursor / Windsurf） |
| **HTTP/SSE MCP** | `python3 -m roundtable.mcp --http --port 8200` | 跨主机或需要持久 HTTP/SSE 端点的 Agent |
| **In-process (Hermes)** | `toolsets: [roundtable]` 或 `RoundtableCore` | 嵌入 Hermes 或 Python 宿主应用 |
| **HTTP Bridge** | `python3 -m roundtable.codex`（默认 `8201`） | Codex CLI、WorkBuddy 等非 MCP HTTP 宿主 |
| **Agent Daemon** | `python3 -m roundtable.agent --agent-id ... --platform ...` | 需要常驻在线心跳与自动接单的运行时 |

> 可靠性实现细节、跨进程订阅、文件锁与回归验收脚本见 [技术可靠性与验证](TECHNICAL_RELIABILITY.md)；Web Viewer 的 `discussion.json` 当前为 `schema_version: 3`（含 `dispatches` 与 `dispatch_summary`），由 `web_sync.py` 跨进程同步。
