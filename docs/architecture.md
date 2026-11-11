# Roundtable 架构图

> 当前定位与路线图见 [产品方向](product/DIRECTION.md)。本页描述已有记录、接入与展示基础设施；角色选择、Agent 执行、模型配置和专业综合由宿主及协调者负责。自动组队、模型路由和决策数据模型仍待验证与实现。

## 系统总览

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          Multi-Agent Roundtable System                           │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌──────────┐  ┌────────┐  │
│  │ Claude Code │  │   Cursor    │  │  Windsurf   │  │ WorkBuddy│  │  Codex │  │
│  │  (stdio)    │  │  (stdio)    │  │  (stdio)    │  │  (stdio) │  │ (HTTP) │  │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └────┬─────┘  └───┬────┘  │
│         │                │                │               │            │        │
│         └────────────────┼────────────────┼───────────────┘            │        │
│                          │  MCP Protocol (stdio)                       │        │
│                          ▼                                             │        │
│  ┌───────────────────────────────────────────────────────┐            │        │
│  │              MCP Server (roundtable.mcp)               │            │        │
│  │                                                       │            │        │
│  │  Tools (25) │ Resources (4) │ Prompts (3)             │◄───────────┘        │
│  │                                                       │  HTTP Bridge         │
│  └───────────────────────────┬───────────────────────────┘  (port 8201)        │
│                              │                                                  │
│                              ▼                                                  │
│  ┌───────────────────────────────────────────────────────────────────────────┐  │
│  │                     roundtable (Core Python Package)                       │  │
│  │                                                                           │  │
│  │  core.py ─── db.py ─── schema.py ─── models.py ─── exceptions.py         │  │
│  │     │                                                                     │  │
│  │     ├── shared DB watcher ──► MCP resource update notifications           │  │
│  │     └── notify.py (platform push)                                         │  │
│  │                                                                           │  │
│  │  SQLite (WAL mode) ─── agents │ agent_inbox │ invitations │ discussions   │  │
│  └───────────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

## 模块依赖关系

```
┌─────────────────────────────────────────────────────────────────────┐
│                        roundtable (Python Package)                  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────┐                                                   │
│  │ __init__.py  │  Public API exports                               │
│  └──────┬───────┘                                                   │
│         │                                                           │
│  ┌──────▼───────┐     ┌─────────────────┐     ┌──────────────────┐ │
│  │   models.py  │◄────│     core.py     │────►│   exceptions.py  │ │
│  │              │     │                 │     │                  │ │
│  │ Discussion   │     │ RoundtableCore  │     │ RoundtableError  │ │
│  │ Participant  │     │                 │     │ DiscussionNotFound│ │
│  │ Speech       │     │ create()        │     │ DiscussionNotActive│
│  │ Finding      │     │ speak()         │     │ InvalidParticipant│ │
│  │ Convergence  │     │ read()          │     │ InvalidSpeechOrder│ │
│  └──────────────┘     │ status()        │     │ InvalidFindingType│ │
│                       │ summarize()     │     │ InvalidReplyTo   │ │
│                       │ end_discussion()│     └──────────────────┘ │
│                       │ list()          │                           │
│  ┌──────────────┐     │ advance()       │     ┌──────────────────┐ │
│  │   db.py      │◄────│ notify()        │────►│   notify.py      │ │
│  │              │     │ on_event()      │     │                  │ │
│  │ RoundtableDB │     └─────────────────┘     │ Notifier         │ │
│  │              │                              │ validate_config()│ │
│  │ SQLite store │                              │                  │ │
│  │ CRUD ops     │                              │ Event types:     │ │
│  │ Schema mgmt  │                              │  speech          │ │
│  │ Agent CRUD   │                              │  round_start     │ │
│  │ Inbox ops    │                              │  round_end       │ │
│  │ Invitations  │                              │  concluded       │ │
│  └──────────────┘                              └──────────────────┘ │
│                                                                     │
│  ┌──────────────────────────────────────┐                           │
│  │         adapters/                    │                           │
│  │                                      │                           │
│  │  ┌──────────────┐  ┌──────────────┐  │                           │
│  │  │  generic.py  │  │  hermes.py   │  │                           │
│  │  │              │  │              │  │                           │
│  │  │ Roundtable   │  │ register_*() │  │                           │
│  │  │ (facade)     │  │ (Hermes MCP) │  │                           │
│  │  └──────────────┘  └──────────────┘  │                           │
│  └──────────────────────────────────────┘                           │
└─────────────────────────────────────────────────────────────────────┘
```

## 核心状态机

```
                    ┌──────────────┐
                    │   创建讨论    │
                    │ create_disc() │
                    └──────┬───────┘
                           │
                           ▼
                    ┌──────────────┐
           ┌───────│    active     │◄──────────┐
           │       │ current_round │           │
           │       └──────┬───────┘           │
           │              │                    │
           │              ▼                    │
           │       ┌──────────────┐           │
           │       │  speak()     │           │
           │       │  add_speech  │           │
           │       └──────┬───────┘           │
           │              │                    │
           │      ┌───────┴────────┐          │
           │      │                │          │
           │      ▼                ▼          │
           │  round_complete   round_start    │
           │  (all spoke)     (1st speech)    │
           │      │                           │
           │      ▼                           │
           │  new_round > max?                │
           │   ├─ No  ───────────────────────┘
           │   │  (advance round)
           │   │
           │   ▼ Yes
           │  ┌──────────────┐
           │  │  auto_conclude│
           │  └──────┬───────┘
           │         │
           ▼         ▼
    ┌──────────┐  ┌──────────────┐
    │ cancelled│  │   concluded  │
    │ (force)  │  │  (normal)    │
    └──────────┘  └──────────────┘
```

## 数据流

```
  User/Agent                Core                  DB (SQLite)
     │                      │                       │
     │── create_disc() ────►│── INSERT disc ────────►│
     │◄── {disc_id} ────────│◄── {Discussion} ───────│
     │                      │                       │
     │── speak(id,who,txt)─►│── validate ───────────►│
     │                      │── INSERT speech ──────►│
     │                      │── check round_complete │
     │                      │── calc convergence ───►│
     │◄── {speech_id,round}─│                       │
     │                      │                       │
     │── read(id) ─────────►│── SELECT speeches ────►│
     │◄── {speeches,...} ───│◄── [Speech,...] ───────│
     │                      │                       │
     │── summarize(id) ────►│── SELECT all ─────────►│
     │                      │── build_structured ───►│
     │◄── {summary} ────────│                       │
     │                      │                       │
     │── end_disc(id) ─────►│── UPDATE status ──────►│
     │◄── {action} ─────────│                       │
     │                      │                       │
     │                      │── Notifier ──────────►│  send_fn(platform,chat,msg)
```

## MCP Server 层

```
┌──────────────────────────────────────────────────────────────────────┐
│              roundtable.mcp (MCP Protocol Layer)                      │
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌──────────────┐                                                    │
│  │ __main__.py  │  python -m roundtable.mcp [--http] [--port 8200]  │
│  │              │  · stdio mode (default) for native MCP clients    │
│  │              │  · HTTP/SSE mode for remote / cross-host           │
│  └──────┬───────┘                                                    │
│         │                                                            │
│  ┌──────▼───────┐                                                    │
│  │  server.py   │  create_server(db_path)                            │
│  │              │  · @list_tools / @call_tool                        │
│  │              │  · @list_resources / @read_resource                │
│  │              │  · @list_prompts / @get_prompt                     │
│  │              │  · DB watch ──► send_resource_updated()            │
│  └──┬─────┬──┬──┘                                                    │
│     │     │  │                                                       │
│  ┌──▼──┐ ┌▼─┐ ┌▼──────┐                                              │
│  │tools│ │re│ │prompts│  Plain dicts → SDK-free, importable for tests│
│  │ .py │ │s │ │  .py  │                                              │
│  └──┬──┘ └┬─┘ └───────┘                                              │
│     │     │                                                          │
│  ┌──▼─────▼──┐    ┌─────────────────┐                                │
│  │  bridges/ │───►│  base.py        │  AgentBridge ABC                │
│  │           │    │  generic.py     │  Shared HTTP implementation      │
│  │           │    │  codex.py       │  Codex defaults, port :8201     │
│  └───────────┘    └─────────────────┘                                │
│                                                                      │
│  ┌──────────────────────────────────────────────┐                    │
│  │  skills/mcp-roundtable/                      │                    │
│  │   ├── install.py        auto-detect platform │                    │
│  │   └── configs/          per-platform JSON    │                    │
│  │       ├── claude-code.json                   │                    │
│  │       ├── cursor.json                        │                    │
│  │       └── windsurf.json                      │                    │
│  └──────────────────────────────────────────────┘                    │
└──────────────────────────────────────────────────────────────────────┘
```

### MCP Tools (25 个)

| 类别       | Tool                          | 用途                                      |
|------------|-------------------------------|-------------------------------------------|
| Agent      | `roundtable_register_agent`   | 注册 agent、transport、skill 与可用性     |
| Agent      | `roundtable_list_agents`      | 按在线状态、skill、availability 查询 agent |
| Agent      | `roundtable_heartbeat`        | 运行时心跳，刷新 last_seen 与 availability |
| Dispatch   | `roundtable_summon_agents`    | 创建/使用 assembling 会议并召集 agent     |
| Dispatch   | `roundtable_dispatch_status`  | 查询 dispatch/summon/readiness 状态       |
| Dispatch   | `roundtable_retry_summon`     | 重投递 pending/failed/timeout summon      |
| Summon     | `roundtable_accept_summon`    | 接受召集并加入参与者                      |
| Summon     | `roundtable_decline_summon`   | 拒绝召集                                  |
| Discussion | `roundtable_create`           | 创建讨论 + 可选传统邀请                   |
| Discussion | `roundtable_list`             | 列出所有讨论，含 assembling               |
| Invitation | `roundtable_invite`           | 传统邀请 agent 加入                       |
| Invitation | `roundtable_accept_invite`    | 接受传统邀请并加入参与者                  |
| Invitation | `roundtable_decline_invite`   | 拒绝传统邀请                              |
| Inbox      | `roundtable_inbox`            | 读取自己的消息（召集 / 邀请 / 轮次提示）  |
| Inbox      | `roundtable_ack_inbox` | 确认成功处理且属于当前 Agent 的消息，支持重试 |
| Speech     | `roundtable_speak`            | 记录发言                                  |
| Speech     | `roundtable_read`             | 读取讨论历史                              |
| Speech     | `roundtable_wait_for_turn`    | 检查是否轮到自己                          |
| Round      | `roundtable_advance`          | 手动推进轮次                              |
| Round      | `roundtable_status`           | 获取讨论状态、收敛度与 dispatch 状态      |
| Conclude   | `roundtable_summarize`        | 获取结构化总结                            |
| Conclude   | `roundtable_end`              | 结束讨论                                  |
| Context    | `roundtable_update_context`   | 完整简报修订、来源、版本冲突检查及历史保留 |
| Findings   | `roundtable_record_finding`   | 记录关联原始发言的共识、分歧或新议题标注 |
| Prompts    | `roundtable_get_prompt`       | 工具及 HTTP 客户端读取同一套阶段提示词 |

### MCP Resources

- `roundtable://agents` — 所有已注册 agent 列表
- `roundtable://discussions` — 所有讨论列表
- `roundtable://discussions/{id}` — 单个讨论状态
- `roundtable://discussions/{id}/transcript` — 完整 markdown 转录
- `roundtable://invitations/{agent_id}` — 某 agent 的待处理邀请

### MCP Prompts

- `coordinator_kickoff` — 协调者启动讨论的模板
- `participant_turn` — 参与者轮到发言时的模板（带历史摘要）
- `coordinator_summarize` — 协调者总结收尾的模板

## 多 Agent 邀请流程

```

## 多 Agent 召集流程

```
  Coordinator              MCP Server                Registry/DB              Agent Bridge
       │                       │                         │                         │
       │── roundtable_summon_agents ────────────────────►│                         │
       │   topic / required_skill / min_accepts           │                         │
       │                       │── create discussion      │                         │
       │                       │   status='assembling' ──►│                         │
       │                       │── select online agents   │                         │
       │                       │   by skill/availability  │                         │
       │                       │── INSERT dispatch ──────►│                         │
       │                       │── INSERT summons ───────►│                         │
       │                       │── push_inbox(summon) ───►│                         │
       │                       │── POST /summon ───────────────────────────────────►│
       │                       │                         │◄── accept_summon ───────│
       │                       │◄──────── roundtable_accept_summon ─────────────────│
       │                       │── INSERT participant ───►│                         │
       │                       │── readiness quorum met ─►│                         │
       │                       │── discussion active ────►│                         │
       │◄── dispatch/readiness/summons ──────────────────│                         │
```

召集是当前主路径：`agents.metadata.skills` 表示 agent 安装的 skill，`availability` 表示运行时状态，`summons` 记录单个 agent 的响应，`dispatches` 记录整次召集的启动策略。`start_policy` 支持 `immediate`、`quorum`、`all`、`timeout`；满足策略后，`assembling` 会议会被激活为 `active`。`roundtable_retry_summon` 复用既有 summon 行做重投递，不创建重复召集记录；显式 `allow_terminal_retry` 可在终态 dispatch 上释放旧 `idempotency_key` 并创建新 dispatch。
  Coordinator              MCP Server                Inbox/DB              Participant
       │                       │                        │                      │
       │── roundtable_create ─►│                        │                      │
       │   (+invite_agents)    │── INSERT discussion ──►│                      │
       │                       │── INSERT invitation ──►│                      │
       │                       │── push_inbox(invite) ─►│                      │
       │◄── {discussion_id} ───│                        │                      │
       │                       │                        │                      │
       │                       │                        │◄── roundtable_inbox ─│
       │                       │                        │── messages[] ───────►│
       │                       │                        │                      │
       │                       │◄────────── roundtable_accept_invite ──────────│
       │                       │── respond_invitation ─►│                      │
       │                       │── INSERT participant ─►│                      │
       │                       │── status='accepted' ──►│                      │
       │                       │── {accepted: true} ───────────────────────────►│
       │                       │                        │                      │
       │                       │   ── on_event ─► send_resource_updated()      │
       │                       │      roundtable://discussions/{id}            │
       │                       │                        │                      │
       │                       │◄────────────── roundtable_speak ──────────────│
       │                       │── INSERT speech ──────►│                      │
       │                       │── check round_complete ►│                      │
       │                       │   (push turn_notice    │                      │
       │                       │    to next speaker)    │                      │
```

## Bridge 架构（非 MCP 平台接入）

Bridge 生命周期接口为 AgentBridge.start/stop。GenericBridge 实现共同的 HTTP 服务、注册、鉴权、邀请策略和可选 webhook；CodexBridge 继承它，只设置 Codex 的平台名称、默认端口和显示名。两者使用同一请求处理器。

Bridge 模式的设计要点：

- **共享状态**：平台通过同一个 SQLite 数据库协调，HTTP Bridge 不执行模型。宿主消费 inbox、运行角色任务并提交发言。
- **传输入口**：原生 MCP 使用 stdio 或 HTTP/SSE；非 MCP 宿主使用 GenericBridge/CodexBridge 的 HTTP 接口；进程内集成可调用 Core 或 adapter。
- **接受策略**：/invite 和 /summon 都只在 accept_policy=auto 时自动接受；其他策略保持待处理，由宿主显式响应。HTTP accepted=true 只表示数据库中的接受状态，过期召集不会标为已接受。
- **可靠启动**：先绑定端口，再登记实际端点；端口冲突不产生新 Agent 记录，登记失败释放监听。port=0 支持系统分配端口，启动后从 bridge.port 读取。
- **心跳**：AgentDaemon 主动刷新；HTTP Bridge 在 health/inbox 请求中刷新。Bridge 自身没有后台心跳或 inbox 监视循环。
- **鉴权与 webhook**：配置的令牌保护读写接口，health 保留公开探测。投递请求携带本地私有令牌，公开 Agent 信息过滤凭据。GenericBridge 的 webhook 转发本实例收到的通知和本实例 Core 产生的事件，不代表监视所有进程的事件。

旧的独立 RoundtableHTTPServer 没有入口或调用者，已移除。AgentBridge 上从未接入执行路径的 on_invitation/generate_speech 占位接口也已移除；自定义模型执行应放在宿主或 adapter 中。

## Web Viewer 状态

Web Viewer 的 `discussion.json` schema v3 额外包含 `dispatches` 与 `dispatch_summary`，用于展示 `assembling` 会议的召集进度、accepted/pending/failed/timeout 计数，以及 dispatch readiness。跨进程更新由 `web_sync.py` 从 SQLite 同步，避免 HTTP bridge 或 AgentDaemon 接受召集后 viewer 状态滞后。

## 调度模式

| 模式        | 实现入口                 | 适用场景                         | 启动方式                         |
|-------------|--------------------------|----------------------------------|----------------------------------|
| Managed     | `ManagedOrchestrator`    | 同平台、同进程或宿主可直接控制 agent | 直接创建 active discussion       |
| Federated   | `FederatedOrchestrator`  | 跨平台、跨进程、HTTP/stdio 混合 agent | registry + summon + heartbeat    |

两种模式共享同一套 `discussions`、`participants`、`dispatches`、`summons` 状态模型。Managed Mode 不依赖 agent registry 选人；Federated Mode 通过 skill、availability、online heartbeat 做发现和召集。

## 数据库 Schema (v5)

```
discussions ──┬─► participants
              ├─► speeches ──► findings
              ├─► convergence_history
              ├─► invitations  ◄─── agents
              └─► dispatches ──► summons ──► summon_events
                                      ▲
                                      │
                                  agent_inbox
```

| 表                | 关键字段                                             | 说明 |
|-------------------|------------------------------------------------------|------|
| discussions       | id, topic, status, current_round, max_rounds         | status 支持 `assembling` |
| participants      | discussion_id + participant (PK), role               | 接受 invite/summon 后加入 |
| speeches          | id, discussion_id, round, participant                | 发言记录 |
| findings          | type (consensus/disagreement/new_point)              | 结构化观点 |
| convergence       | discussion_id + round (PK), score                    | 收敛度历史 |
| agents            | agent_id (PK), platform, transport, endpoint, metadata | metadata 含 skills/availability |
| agent_inbox       | id, agent_id, type, payload, read_at                 | summon/invite/turn 消息 |
| invitations       | discussion_id + agent_id (UNIQUE), status            | 传统邀请路径 |
| dispatches        | id, discussion_id, mode, start_policy, status        | 一次召集/调度 |
| summons           | id, dispatch_id, agent_id, status, expires_at        | 单 agent 召集生命周期 |
| summon_events     | summon_id, dispatch_id, event, payload               | 可审计事件流 |

迁移由 `PRAGMA user_version` + `_MIGRATIONS` 列表管理；新增迁移仅需 append 函数。
v4 在 v3 召集表基础上新增查询索引：`idx_dispatches_coordinator`、`idx_summons_timeout`、`idx_inbox_discussion`，用于协调者过滤、过期 summon 扫描和 discussion 维度 inbox 同步。

v5 增加 `context_revisions`，以 `(discussion_id, revision)` 为主键，保存 context、source、reason、created_at。旧会议在首次修订时保留 v0 背景；更新在事务中核对 expected_revision，随后追加版本并更新 discussions.context。读取和提示词使用一致的数据库快照。已结束会议不修改背景，需通过后续会议重新评审。

read、status、summarize 返回 conclusion；read 与 summarize 还提供 context_history。摘要和 transcript 导出保留完整结论。`current_round` 是引擎游标，`total_rounds` 与 `completed_rounds` 从实际参与者发言计算，不计开场和空轮。结论补写、背景修订和观点标注会发出资源更新事件。

观点标注是主持人/参与者的显式记录，必须引用当前会议内存在的发言，相同内容与引用的重试去重。接口不自动执行语义归纳或证据验证。模型运行仍由宿主负责；HTTP 的 roundtable_get_prompt 只返回提示词。CodexBridge 与 GenericBridge 的 `/speak` 和 `/tool` 发言共用工具处理器，保持下一位通知一致。

## 数据流

```
  User/Agent                Core                  DB (SQLite)
     │                      │                       │
     │── create_disc() ────►│── INSERT disc ────────►│
     │◄── {disc_id} ────────│◄── {Discussion} ───────│
     │                      │                       │
     │── speak(id,who,txt)─►│── validate ───────────►│
     │                      │── INSERT speech ──────►│
     │                      │── check round_complete │
     │                      │── calc convergence ───►│
     │                      │── DB commit/watch ──► MCP resource_updated
     │◄── {speech_id,round}─│                       │
     │                      │                       │
     │── read(id) ─────────►│── SELECT speeches ────►│
     │◄── {speeches,...} ───│◄── [Speech,...] ───────│
     │                      │                       │
     │── summarize(id) ────►│── SELECT all ─────────►│
     │                      │── build_structured ───►│
     │◄── {summary} ────────│                       │
     │                      │                       │
     │── end_disc(id) ─────►│── UPDATE status ──────►│
     │                      │── DB commit/watch ──► MCP resource_updated
     │◄── {action} ─────────│                       │
     │                      │                       │
     │                      │── Notifier ──────────►│  send_fn(platform,chat,msg)
```

## 部署形态

| 形态                     | 启动                                       | 适用场景                       |
|--------------------------|-------------------------------------------|--------------------------------|
| **stdio MCP**            | `python -m roundtable.mcp`                | 单机多 agent，本地编辑器       |
| **HTTP/SSE MCP**         | `python -m roundtable.mcp --http --port`  | 跨主机、远程 agent             |
| **In-process (Hermes)**  | `from roundtable.adapters.hermes import…` | 嵌入到 Hermes 主程序           |
| **HTTP Bridge (Codex)**  | `python -m roundtable.codex` (port 8201)  | OpenAI Codex CLI 等非 MCP 平台 |
| **Agent Daemon**         | `python -m roundtable.agent --agent-id ... --platform ...` | stdio/轮询型 agent runtime |

## 测试覆盖率 (v0.1.0a1)

| 模块                  | 语句数 | 未覆盖 | 覆盖率 |
|-----------------------|--------|--------|--------|
| core.py               | 386    | 1      | 99%    |
| db.py                 | 205    | 19     | 91%    |
| notify.py             | 113    | 9      | 92%    |
| models.py             | 53     | 0      | 100%   |
| exceptions.py         | 7      | 0      | 100%   |
| adapters/generic.py   | 60     | 42     | 30%    |
| adapters/hermes.py    | 100    | 60     | 40%    |
| mcp/tools.py          | —      | —      | tested via tests/mcp/test_tools.py (7 cases) |
| mcp/* (inbox/invite)  | —      | —      | tested via tests/mcp/test_inbox.py (7 cases) |
| **总计**              | **932**| **131**| **86%**|


### MCP 运行时可靠性

stdio 与 SSE 入口统一使用包含订阅能力的初始化选项。每个会话的独立 SQLite 连接检查 data_version，将其他进程的写入合并为订阅资源的失效通知；通知使用实际订阅 URI。会话退出时取消观察任务并清理订阅。Core 的 on_event 仍可供其他宿主集成，但不再是 MCP 跨进程通知的唯一来源。

Daemon 只消费召集/邀请，读取时不标记已读，成功处理后再确认。宿主处理轮次消息时采用相同的读取—处理—确认流程。旧版读取即确认行为保留兼容。协议测试使用实际 stdio/SSE 客户端及干净 wheel 环境，具体语义和限制见 [技术可靠性说明](TECHNICAL_RELIABILITY.md)。
