# 技术方案：Agent 圆桌讨论功能 (Roundtable Discussion)

> 技术总监 码飞 | 2026-05-20 | v1.0
> 基于饼哥 PRD v1.0 设计技术实现方案

---

## 一、架构决策

### 1.1 选定方案：方案 B — 独立 Roundtable Skill

**理由**：

1. **关注点分离** — 讨论是多向交流，kanban 是单向任务管理，概念不应混在一起
2. **零侵入** — 不修改 kanban schema，不影响现有工作流
3. **独立演进** — 作为 skill 可以独立发布、独立版本控制
4. **复用基础设施** — 共享 kanban 的 SQLite 连接路径和 profile 系统，但不共享 schema

**技术路径**：
```
roundtable skill（独立模块）
├── tools/roundtable_tools.py    — 注册到 Hermes 工具系统
├── agent/skills/roundtable/     — Skill 文档（流程指导）
└── hermes_cli/roundtable_db.py  — SQLite 数据层（独立表）
```

### 1.2 为什么不选方案 A

| 顾虑 | 说明 |
|------|------|
| Schema 污染 | kanban 的 `task_comments` 表是单向追加，没有 `reply_to`、`round` 字段。加这些字段会破坏 kanban 的简洁性 |
| 概念混乱 | 任务评论和讨论发言是两个不同概念，混用会导致语义不清 |
| 维护负担 | kanban 已经 1100+ 行代码，再加 800 行讨论逻辑，模块会膨胀 |

---

## 二、数据模型

### 2.1 数据库选择

使用**独立 SQLite 数据库**：`~/.hermes/roundtable.db`

**为什么不复用 kanban.db**：
- 独立数据库便于备份、迁移、调试
- 避免与 kanban 事务冲突
- 可以独立控制 WAL 模式和 PRAGMA

### 2.2 Schema 设计

```sql
-- 启用 WAL 模式（并发读友好）
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- 讨论主表
CREATE TABLE discussions (
    id TEXT PRIMARY KEY,                    -- 'rt_' + 8位hex
    topic TEXT NOT NULL,                    -- 讨论话题
    context TEXT,                           -- 背景信息（协调者提供的上下文）
    status TEXT DEFAULT 'active'
        CHECK(status IN ('active', 'concluded', 'cancelled')),
    max_rounds INTEGER DEFAULT 5,           -- 最大轮次
    current_round INTEGER DEFAULT 0,        -- 当前轮次（0=开场白阶段）
    speech_order TEXT DEFAULT 'fixed'       -- 发言顺序策略
        CHECK(speech_order IN ('fixed', 'random', 'priority', 'free')),
    created_by TEXT NOT NULL,               -- 发起人 profile
    created_at INTEGER NOT NULL,            -- Unix timestamp
    concluded_at INTEGER,
    conclusion TEXT,                        -- 最终结论文档（Markdown）
    convergence_score REAL,                 -- 最终收敛度 0.0-1.0
    output_path TEXT                        -- 结论文档保存路径
);

-- 参与者表
CREATE TABLE participants (
    discussion_id TEXT NOT NULL,
    participant TEXT NOT NULL,              -- profile name（如 'bingge', 'mafei'）
    role TEXT,                              -- 角色描述（如 '产品总监'）
    perspective TEXT,                       -- 角色视角提示（如 '关注用户体验'）
    display_name TEXT,                      -- 显示名（如 '饼哥'）
    joined_at INTEGER NOT NULL,
    is_active INTEGER DEFAULT 1,            -- 是否活跃（支持中途退出）
    PRIMARY KEY (discussion_id, participant),
    FOREIGN KEY (discussion_id) REFERENCES discussions(id) ON DELETE CASCADE
);

-- 发言表
CREATE TABLE speeches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    discussion_id TEXT NOT NULL,
    round INTEGER NOT NULL,                 -- 轮次（0=开场白，1-N=正式讨论）
    participant TEXT NOT NULL,
    content TEXT NOT NULL,                  -- 发言内容（Markdown）
    reply_to INTEGER,                       -- 引用的发言 ID（可选）
    created_at INTEGER NOT NULL,
    FOREIGN KEY (discussion_id) REFERENCES discussions(id) ON DELETE CASCADE,
    FOREIGN KEY (reply_to) REFERENCES speeches(id)
);

-- 发现记录表（共识/分歧/新观点）
CREATE TABLE findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    discussion_id TEXT NOT NULL,
    type TEXT NOT NULL
        CHECK(type IN ('consensus', 'disagreement', 'new_point')),
    content TEXT NOT NULL,
    round INTEGER NOT NULL,                 -- 在哪一轮发现的
    related_speeches TEXT,                  -- JSON array of speech IDs
    FOREIGN KEY (discussion_id) REFERENCES discussions(id) ON DELETE CASCADE
);

-- 收敛度历史
CREATE TABLE convergence_history (
    discussion_id TEXT NOT NULL,
    round INTEGER NOT NULL,
    score REAL NOT NULL,                    -- 0.0-1.0
    consensus_count INTEGER,
    disagreement_count INTEGER,
    new_point_count INTEGER,
    PRIMARY KEY (discussion_id, round),
    FOREIGN KEY (discussion_id) REFERENCES discussions(id) ON DELETE CASCADE
);

-- 索引
CREATE INDEX idx_speeches_discussion ON speeches(discussion_id, round);
CREATE INDEX idx_speeches_participant ON speeches(discussion_id, participant);
CREATE INDEX idx_findings_discussion ON findings(discussion_id, type);
```

### 2.3 ID 生成规则

- Discussion ID: `rt_` + 8位hex（如 `rt_a1b2c3d4`）
- Speech ID: 自增整数
- 与 kanban 的 `t_` 前缀区分，避免混淆

---

## 三、工具设计

### 3.1 工具清单

注册 7 个工具到 Hermes 工具系统，通过 `tools/registry.py` 自动发现。

```python
# tools/roundtable_tools.py

from tools.registry import registry

# 1. roundtable_init — 创建讨论
registry.register(
    name="roundtable_init",
    toolset="roundtable",
    schema={
        "name": "roundtable_init",
        "description": "Create a new roundtable discussion with topic and participants",
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Discussion topic"},
                "participants": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "profile": {"type": "string"},
                            "role": {"type": "string"},
                            "perspective": {"type": "string"},
                            "display_name": {"type": "string"}
                        },
                        "required": ["profile"]
                    },
                    "description": "List of participant profiles"
                },
                "context": {"type": "string", "description": "Background context"},
                "max_rounds": {"type": "integer", "default": 5},
                "speech_order": {"type": "string", "enum": ["fixed", "random", "priority", "free"], "default": "fixed"},
                "output_path": {"type": "string", "description": "Path to save conclusion document"}
            },
            "required": ["topic", "participants"]
        }
    },
    handler=_handle_init,
    toolset="roundtable",
)

# 2. roundtable_speak — 发言
# 3. roundtable_read — 读取历史发言
# 4. roundtable_status — 查看讨论状态
# 5. roundtable_summarize — 生成结论文档
# 6. roundtable_end — 结束讨论
# 7. roundtable_list — 列出所有讨论
```

### 3.2 工具详细规格

#### roundtable_init(topic, participants, context?, max_rounds?, speech_order?, output_path?)

**功能**：创建讨论实例，注册参与者

**返回**：
```json
{
    "ok": true,
    "discussion_id": "rt_a1b2c3d4",
    "topic": "数据库选型",
    "participants": ["bingge", "mafei", "xiaosu"],
    "max_rounds": 5,
    "speech_order": "fixed",
    "status": "active"
}
```

#### roundtable_speak(discussion_id, participant, content, reply_to?)

**功能**：发言，自动推进轮次

**轮次推进逻辑**：
1. 每个参与者按顺序发言
2. 当所有参与者都完成一轮发言后，`current_round` 自动 +1
3. 达到 `max_rounds` 时，讨论状态变为 `concluded`

**返回**：
```json
{
    "ok": true,
    "speech_id": 42,
    "round": 2,
    "participant": "mafei",
    "next_speaker": "xiaosu",
    "round_complete": false,
    "discussion_complete": false
}
```

#### roundtable_read(discussion_id, since_round?, participant?)

**功能**：读取历史发言

**返回**：
```json
{
    "ok": true,
    "discussion_id": "rt_a1b2c3d4",
    "topic": "数据库选型",
    "current_round": 2,
    "speeches": [
        {"id": 1, "round": 0, "participant": "coordinator", "content": "..."},
        {"id": 2, "round": 1, "participant": "bingge", "content": "...", "reply_to": null},
        ...
    ]
}
```

#### roundtable_status(discussion_id)

**功能**：查看讨论状态和收敛度

**返回**：
```json
{
    "ok": true,
    "discussion_id": "rt_a1b2c3d4",
    "status": "active",
    "current_round": 2,
    "max_rounds": 5,
    "convergence_score": 0.67,
    "consensus_points": ["使用 PostgreSQL", "需要读写分离"],
    "disagreement_points": ["是否用 ORM"],
    "new_points": ["考虑 TimescaleDB 时序扩展"],
    "speech_count": 12,
    "next_speaker": "xiaosu"
}
```

#### roundtable_summarize(discussion_id)

**功能**：生成结论文档（Markdown）

**流程**：
1. 读取所有发言和发现
2. 提取共识点、分歧点、待办事项
3. 生成结构化 Markdown 文档
4. 保存到指定路径（或默认路径）
5. 更新 `discussions.conclusion` 字段

**返回**：
```json
{
    "ok": true,
    "discussion_id": "rt_a1b2c3d4",
    "conclusion_path": "/Users/parsifal/Repo/Monorepo/roast-master/docs/product/roundtable-数据库选型.md",
    "consensus_count": 3,
    "disagreement_count": 1,
    "action_items": 2
}
```

#### roundtable_end(discussion_id, force?)

**功能**：结束讨论

#### roundtable_list(status?, limit?)

**功能**：列出讨论

---

## 四、通信机制

### 4.1 核心问题

Agent 之间如何交换发言？这是圆桌讨论最关键的技术问题。

### 4.2 方案对比

| 方案 | 实现方式 | 优点 | 缺点 |
|------|----------|------|------|
| A. 顺序子代理 | 协调者依次 `delegate_task` 每个参与者 | 简单，上下文完整 | 串行，慢；协调者是瓶颈 |
| B. 并行子代理 + 轮次同步 | 每轮并行 `delegate_task` 所有参与者 | 快 | 需要轮次同步机制 |
| C. 共享数据库 + 轮询 | 参与者写入 SQLite，其他参与者轮询读取 | 解耦，可扩展 | 轮询延迟；需要进程协调 |
| D. 共享数据库 + 协调者驱动 | 协调者读取发言，注入到每个参与者的 prompt | 简单可靠 | 协调者是单点 |

### 4.3 选定方案：D — 协调者驱动模式

**理由**：
1. **最简单可靠** — 不需要进程间通信
2. **上下文完整** — 协调者可以把完整讨论历史注入每个参与者的 prompt
3. **符合 Hermes 现有模型** — `delegate_task` 是同步的，天然支持顺序执行
4. **易于调试** — 所有发言都在 SQLite 中，可追溯

### 4.4 执行流程

```
协调者（发起人）
    │
    ├── roundtable_init(topic, participants)
    │   → 创建讨论，返回 discussion_id
    │
    ├── [Round 0: 开场白]
    │   └── 协调者写入背景说明 (roundtable_speak)
    │
    ├── [Round 1: 第一轮讨论]
    │   │
    │   ├── 读取历史 (roundtable_read)
    │   │
    │   ├── delegate_task → Agent A (产品)
    │   │   prompt: "你是圆桌讨论参与者，角色是产品总监。
    │   │            讨论话题：XXX
    │   │            以下是之前的发言：...
    │   │            请发表你的观点。"
    │   │   → Agent A 调用 roundtable_speak(...)
    │   │
    │   ├── delegate_task → Agent B (设计)
    │   │   prompt: "...以下是之前的发言（含A的新发言）..."
    │   │   → Agent B 调用 roundtable_speak(...)
    │   │
    │   └── delegate_task → Agent C (开发)
    │       prompt: "...以下是之前的发言（含A和B的新发言）..."
    │       → Agent C 调用 roundtable_speak(...)
    │
    ├── [Round 2..N: 后续轮次]
    │   └── 重复上述流程
    │
    ├── [收敛检测]
    │   └── 每轮结束后检查 convergence_score
    │       → 如果 > 0.8 或达到 max_rounds，进入总结
    │
    └── [总结]
        └── roundtable_summarize(discussion_id)
            → 生成结论文档
```

### 4.5 参与者 Prompt 模板

```python
ROUNDTABLE_SPEAKER_PROMPT = """
你正在参与一个圆桌讨论。

## 讨论信息
- 话题：{topic}
- 背景：{context}
- 当前轮次：Round {current_round} / {max_rounds}
- 你的角色：{role}（{display_name}）
- 你的视角：{perspective}

## 讨论历史
{formatted_history}

## 你的任务
请从你的角色视角出发，发表对这个话题的观点。
- 可以引用或回应其他参与者的发言
- 保持简洁有力，200-500字
- 如果你同意某个观点，明确表示认同
- 如果你不同意，说明理由并提出替代方案

发言后，请调用 roundtable_speak 工具记录你的发言。
"""
```

---

## 五、收敛度算法

### 5.1 计算方法

每轮结束后，由协调者的 LLM 评估收敛度：

```python
def evaluate_convergence(discussion_id: str) -> dict:
    """评估讨论收敛度"""
    # 1. 读取本轮所有发言
    # 2. 使用 LLM 提取：
    #    - 共识点（consensus）：多人认同的观点
    #    - 分歧点（disagreement）：意见不同的地方
    #    - 新观点（new_point）：本轮新提出的话题
    # 3. 计算收敛度
    #    convergence = consensus / (consensus + disagreement)
    # 4. 记录到 convergence_history
    return {
        "score": 0.67,
        "consensus": ["共识1", "共识2"],
        "disagreement": ["分歧1"],
        "new_points": ["新观点1"]
    }
```

### 5.2 收敛评估 Prompt

```python
CONVERGENCE_EVAL_PROMPT = """
分析以下圆桌讨论的第 {round} 轮发言，提取：

1. **共识点**：多个参与者明确认同的观点
2. **分歧点**：参与者意见不同的地方
3. **新观点**：本轮新提出的话题或角度

输出 JSON：
{{
    "consensus": ["观点1", "观点2"],
    "disagreement": ["分歧1"],
    "new_points": ["新观点1"]
}}

发言记录：
{speeches}
"""
```

### 5.3 提前终止条件

| 条件 | 说明 |
|------|------|
| 收敛度 > 0.8 | 共识率高，讨论充分 |
| 达到最大轮次 | 防止无限讨论 |
| 协调者手动终止 | 紧急情况 |
| 参与者投票终止 | 所有参与者都表示"可以结束了" |

---

## 六、与现有系统集成

### 6.1 Skill 文档

创建 `~/.hermes/profiles/mafei/skills/software-development/roundtable/SKILL.md`：

```markdown
---
name: roundtable
description: "Multi-agent roundtable discussion — topic-driven multi-round debate with convergence detection and conclusion generation"
version: 1.0.0
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [discussion, multi-agent, collaboration, debate]
    related_skills: [kanban-worker, kanban-orchestrator]
---

# Roundtable Discussion Skill

## 概述
让多个 Agent 围绕一个话题进行多轮交流讨论，最终产出结论。

## 使用场景
- 技术方案评审
- 竞品分析讨论
- Bug 根因分析
- 产品需求讨论
- 架构决策

## 流程
1. 发起讨论：roundtable_init
2. 多轮发言：roundtable_speak（每个参与者轮流）
3. 读取历史：roundtable_read（参与者看到完整讨论）
4. 状态查看：roundtable_status
5. 收敛检测：每轮自动评估
6. 生成结论：roundtable_summarize
7. 结束讨论：roundtable_end

## 参与者 Prompt 模板
...
```

### 6.2 Toolset 注册

在 `toolsets.py` 中添加 roundtable toolset：

```python
TOOLSETS["roundtable"] = {
    "name": "roundtable",
    "description": "Multi-agent roundtable discussion tools",
    "tools": [
        "roundtable_init",
        "roundtable_speak",
        "roundtable_read",
        "roundtable_status",
        "roundtable_summarize",
        "roundtable_end",
        "roundtable_list",
    ],
}
```

### 6.3 与 Kanban 集成

讨论可以关联到 kanban task：

```python
# 发起讨论时关联 task
roundtable_init(
    topic="数据库选型",
    participants=[...],
    # 可选：关联到 kanban task
)

# 讨论结束后，自动将结论写入 task comment
kanban_comment(
    task_id=task_id,
    body=f"圆桌讨论结论已生成：{conclusion_path}"
)
```

### 6.4 飞书集成（P2）

讨论过程可以实时同步到飞书群：

```python
# 每轮发言后，发送到飞书群
feishu_send(
    chat_id=feishu_group_id,
    message=f"[Round {round}] {participant}({role}): {content}"
)
```

---

## 七、提 PR 规划

### 7.1 文件清单

```
hermes-agent/
├── tools/roundtable_tools.py           # 工具注册 + 处理器（~500行）
├── hermes_cli/roundtable_db.py         # SQLite 数据层（~300行）
├── tests/tools/test_roundtable_tools.py # 单元测试（~200行）
├── tests/test_roundtable_db.py         # 数据层测试（~150行）
├── skills/                             # 内置 skill 文档
│   └── roundtable/SKILL.md
└── toolsets.py                         # 添加 roundtable toolset
```

### 7.2 PR 拆分策略

| PR | 内容 | 依赖 |
|----|------|------|
| PR 1 | 数据层：roundtable_db.py + 测试 | 无 |
| PR 2 | 工具层：roundtable_tools.py + 测试 | PR 1 |
| PR 3 | Skill 文档 + toolsets.py 注册 | PR 2 |
| PR 4 | 集成测试 + 文档 | PR 3 |

### 7.3 PR 模板

```markdown
## feat: roundtable discussion — multi-agent topic debate

### Changes
- Add `roundtable_db.py` — SQLite schema + CRUD for discussions, speeches, findings
- Add `roundtable_tools.py` — 7 tools registered via `tools/registry.py`
- Add `roundtable` toolset to `toolsets.py`
- Add `skills/roundtable/SKILL.md` — usage guide and prompt templates

### Testing
- Unit tests for all CRUD operations
- Integration test: init → speak (3 participants × 3 rounds) → summarize
- Edge cases: empty participants, max rounds exceeded, concurrent access

### Breaking Changes
None — new feature, no existing code modified.

### Screenshots
N/A — CLI tooling.
```

---

## 八、实现计划

### Phase 1：MVP（1 周）

**Day 1-2：数据层**
- [ ] `roundtable_db.py` — Schema 创建、CRUD 操作
- [ ] 单元测试覆盖所有表操作
- [ ] ID 生成、时间戳处理

**Day 3-4：工具层**
- [ ] `roundtable_tools.py` — 7 个工具的 handler
- [ ] 轮次推进逻辑
- [ ] 发言顺序策略实现
- [ ] 集成测试

**Day 5：协调者驱动逻辑**
- [ ] 参与者 prompt 模板
- [ ] delegate_task 调用流程
- [ ] 收敛度评估（简化版：基于 LLM）

**Day 6-7：Skill + 集成**
- [ ] SKILL.md 文档
- [ ] toolsets.py 注册
- [ ] 端到端测试
- [ ] 文档完善

### Phase 2：增强（第 2 周）

- [ ] 引用回复支持（`reply_to` 字段已预留）
- [ ] 收敛度算法优化（更精确的共识/分歧检测）
- [ ] 发言顺序策略（random, priority）
- [ ] 与 kanban task 关联

### Phase 3：扩展（第 3 周）

- [ ] 飞书群实时同步
- [ ] CLI 命令行支持（`hermes roundtable start ...`）
- [ ] 并行讨论管理
- [ ] 讨论模板库

---

## 九、技术风险与应对

| 风险 | 影响 | 应对 |
|------|------|------|
| LLM 调用成本 | 每轮 N 个参与者 × M 轮 = N×M 次调用 | 设置合理的 max_rounds（默认 5）；支持提前终止 |
| 上下文过长 | 发言历史可能超过 context window | 支持 `since_round` 参数裁剪；压缩历史 |
| 并发安全 | 多个协调者同时发起讨论 | SQLite WAL 模式 + 事务隔离 |
| 参与者"跑题" | LLM 可能偏离话题 | prompt 中强调话题；每轮收敛检测 |
| 讨论无限循环 | 收敛度始终不高 | max_rounds 硬限制 + 协调者手动终止 |

---

## 十、验收标准映射

| PRD 验收项 | 技术实现 | 优先级 |
|-----------|---------|--------|
| 发起讨论 | `roundtable_init` 工具 | P0 |
| 多轮发言 | 轮次推进逻辑 + `delegate_task` 循环 | P0 |
| 发言可见性 | `roundtable_read` 返回完整历史 | P0 |
| 引用回复 | `reply_to` 字段 + prompt 中的引用格式 | P1 |
| 自动总结 | `roundtable_summarize` + LLM 生成 | P0 |
| 收敛检测 | `convergence_history` 表 + 评估算法 | P1 |
| 提前终止 | `force` 参数 + 状态检查 | P1 |
| 飞书同步 | 飞书消息发送集成 | P2 |
| CLI 支持 | `hermes roundtable` 子命令 | P2 |
| 并行讨论 | 独立 `discussion_id` 隔离 | P2 |

---

## 附录 A：代码示例 — 完整讨论流程

```python
# 协调者发起讨论
result = roundtable_init(
    topic="数据库选型：PostgreSQL vs MySQL vs TiDB",
    context="我们的电商系统需要支持高并发读写，数据量预计 1TB+",
    participants=[
        {"profile": "bingge", "role": "产品总监", "perspective": "关注用户体验和业务需求", "display_name": "饼哥"},
        {"profile": "mafei", "role": "技术总监", "perspective": "关注技术可行性和性能", "display_name": "码飞"},
        {"profile": "xiaosu", "role": "设计师", "perspective": "关注数据展示和查询体验", "display_name": "像素姐"},
    ],
    max_rounds=3,
    speech_order="fixed",
    output_path="/Users/parsifal/Repo/Monorepo/roast-master/docs/product/roundtable-数据库选型.md",
)
discussion_id = result["discussion_id"]

# Round 0: 开场白（协调者）
roundtable_speak(discussion_id, "coordinator", "今天讨论数据库选型...")

# Round 1: 第一轮
# 读取历史
history = roundtable_read(discussion_id)

# 依次让每个参与者发言
for participant in ["bingge", "mafei", "xiaosu"]:
    delegate_task(
        goal=f"参与圆桌讨论，话题：{topic}",
        context=f"你是{participant}，请调用 roundtable_speak 工具发言。\n\n讨论历史：\n{history}",
    )

# 检查收敛度
status = roundtable_status(discussion_id)

# Round 2-3: 重复...

# 生成结论
roundtable_summarize(discussion_id)
```

---

## 附录 B：目录结构

```
~/.hermes/
├── roundtable.db                        # 圆桌讨论数据库
├── profiles/mafei/
│   └── skills/
│       └── software-development/
│           └── roundtable/
│               └── SKILL.md            # Skill 文档
└── hermes-agent/
    ├── tools/
    │   └── roundtable_tools.py          # 工具实现
    ├── hermes_cli/
    │   └── roundtable_db.py             # 数据层
    ├── tests/
    │   ├── tools/test_roundtable_tools.py
    │   └── test_roundtable_db.py
    └── toolsets.py                      # 工具集注册
```
