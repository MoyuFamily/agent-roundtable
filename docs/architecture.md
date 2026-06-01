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
│  │  Tools (15) │ Resources (4) │ Prompts (3)             │◄───────────┘        │
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

### MCP Tools (15 个)

| 类别       | Tool                          | 用途                              |
|------------|-------------------------------|-----------------------------------|
| Agent      | `roundtable_register_agent`   | 注册 agent，使其可被发现          |
| Agent      | `roundtable_list_agents`      | 查询在线 agent 列表               |
| Discussion | `roundtable_create`           | 创建讨论 + 同步发邀请             |
| Discussion | `roundtable_list`             | 列出所有讨论                       |
| Invitation | `roundtable_invite`           | 邀请 agent 加入                   |
| Invitation | `roundtable_accept_invite`    | 接受邀请并加入参与者              |
| Invitation | `roundtable_decline_invite`   | 拒绝邀请                          |
| Inbox      | `roundtable_inbox`            | 读取自己的消息（邀请 / 轮次提示） |
| Speech     | `roundtable_speak`            | 记录发言                          |
| Speech     | `roundtable_read`             | 读取讨论历史                      |
| Speech     | `roundtable_wait_for_turn`    | 检查是否轮到自己                  |
| Round      | `roundtable_advance`          | 手动推进轮次                      |
| Round      | `roundtable_status`           | 获取讨论状态 + 收敛度             |
| Conclude   | `roundtable_summarize`        | 获取结构化总结                    |
| Conclude   | `roundtable_end`              | 结束讨论                          |

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
- **解耦邀请与执行**：邀请进 inbox，agent 自己 poll，避免长连接和事件丢失

## 数据库 Schema (v2)

```
discussions ──┬─► participants
              ├─► speeches ──► findings
              ├─► convergence_history
              └─► invitations  ◄─── agents
                                      │
                                      └─► agent_inbox
```

| 表              | 关键字段                                       | v2 新增 |
|-----------------|-----------------------------------------------|---------|
| discussions     | id, topic, status, current_round, max_rounds  |         |
| participants    | discussion_id + participant (PK), role        |         |
| speeches        | id, discussion_id, round, participant         |         |
| findings        | type (consensus/disagreement/new_point)       |         |
| convergence     | discussion_id + round (PK), score             |         |
| **agents**      | agent_id (PK), platform, transport, endpoint  | ✓       |
| **agent_inbox** | id, agent_id, type, payload, read_at          | ✓       |
| **invitations** | discussion_id + agent_id (UNIQUE), status     | ✓       |

迁移由 `PRAGMA user_version` + `_MIGRATIONS` 列表管理；新增迁移仅需 append 函数。

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
