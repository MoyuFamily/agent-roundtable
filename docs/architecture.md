# Roundtable 架构图

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
│  │  Tools (21) │ Resources (4) │ Prompts (3)             │◄───────────┘        │
│  │                                                       │  HTTP Bridge         │
│  └───────────────────────────┬───────────────────────────┘  (port 8201)        │
│                              │                                                  │
│                              ▼                                                  │
│  ┌───────────────────────────────────────────────────────────────────────────┐  │
│  │                     roundtable (Core Python Package)                       │  │
│  │                                                                           │  │
│  │  core.py ─── db.py ─── schema.py ─── models.py ─── exceptions.py         │  │
│  │     │                                                                     │  │
│  │     ├── on_event callback ──► MCP resource update notifications           │  │
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
│  │              │  · on_event ──► send_resource_updated()            │
│  └──┬─────┬──┬──┘                                                    │
│     │     │  │                                                       │
│  ┌──▼──┐ ┌▼─┐ ┌▼──────┐                                              │
│  │tools│ │re│ │prompts│  Plain dicts → SDK-free, importable for tests│
│  │ .py │ │s │ │  .py  │                                              │
│  └──┬──┘ └┬─┘ └───────┘                                              │
│     │     │                                                          │
│  ┌──▼─────▼──┐    ┌─────────────────┐                                │
│  │  bridges/ │───►│  base.py        │  AgentBridge ABC                │
│  │           │    │  codex.py       │  HTTP server :8201              │
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

### MCP Tools (21 个)

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
| Speech     | `roundtable_speak`            | 记录发言                                  |
| Speech     | `roundtable_read`             | 读取讨论历史                              |
| Speech     | `roundtable_wait_for_turn`    | 检查是否轮到自己                          |
| Round      | `roundtable_advance`          | 手动推进轮次                              |
| Round      | `roundtable_status`           | 获取讨论状态、收敛度与 dispatch 状态      |
| Conclude   | `roundtable_summarize`        | 获取结构化总结                            |
| Conclude   | `roundtable_end`              | 结束讨论                                  |

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

```
┌────────────────────────────────────────────────────────────────────┐
│                  AgentBridge (abstract base)                        │
│                                                                    │
│   start() / stop() / on_invitation() / generate_speech()           │
└────────────────────────┬───────────────────────────────────────────┘
                         │
              ┌──────────┴──────────┐
              ▼                     ▼
   ┌──────────────────┐   ┌──────────────────┐
   │  CodexBridge     │   │  (future)        │
   │  HTTP :8201      │   │  WorkBuddy/...   │
   │                  │   │                  │
   │  POST /invite    │   │                  │
   │  POST /summon    │   │                  │
   │  POST /tool      │   │                  │
   └─────┬────────────┘   └──────────────────┘
         │
         ▼
   ┌──────────────────────────────────┐
   │  在 Codex CLI 进程中调用本地 API │
   │  共享 SQLite DB, 通过 inbox 协调 │
   └──────────────────────────────────┘
```

Bridge 模式的设计要点：
- **共享状态总线**：所有平台都通过同一个 SQLite DB 协调，不需要中间消息队列
- **三种传输模式**：stdio（原生 MCP）/ HTTP（远程或非 MCP 平台）/ in-process（Hermes adapter）
- **解耦召集与执行**：召集/邀请都进 inbox；HTTP bridge 也可通过 `/summon` 自动接受
- **运行时注册**：`GenericBridge`、`CodexBridge` 和 `AgentDaemon` 启动时注册 `agent-roundtable` skill，并通过 heartbeat 刷新在线状态
- **可选桥接鉴权**：HTTP bridge 可配置 bearer token；MCP 投递 `/invite`、`/summon`、`/turn` 时会自动携带本地私有 token，公开 agent 列表会过滤该字段

## Web Viewer 状态

Web Viewer 的 `discussion.json` schema v3 额外包含 `dispatches` 与 `dispatch_summary`，用于展示 `assembling` 会议的召集进度、accepted/pending/failed/timeout 计数，以及 dispatch readiness。跨进程更新由 `web_sync.py` 从 SQLite 同步，避免 HTTP bridge 或 AgentDaemon 接受召集后 viewer 状态滞后。

## 调度模式

| 模式        | 实现入口                 | 适用场景                         | 启动方式                         |
|-------------|--------------------------|----------------------------------|----------------------------------|
| Managed     | `ManagedOrchestrator`    | 同平台、同进程或宿主可直接控制 agent | 直接创建 active discussion       |
| Federated   | `FederatedOrchestrator`  | 跨平台、跨进程、HTTP/stdio 混合 agent | registry + summon + heartbeat    |

两种模式共享同一套 `discussions`、`participants`、`dispatches`、`summons` 状态模型。Managed Mode 不依赖 agent registry 选人；Federated Mode 通过 skill、availability、online heartbeat 做发现和召集。

## 数据库 Schema (v4)

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
     │                      │── on_event(speech) ──► MCP resource_updated
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
     │                      │── on_event(end) ─────► MCP resource_updated
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
