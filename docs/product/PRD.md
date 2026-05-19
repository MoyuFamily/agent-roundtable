# PRD: Agent 圆桌讨论功能 (Roundtable Discussion)

> 产品总监 饼哥 | 2026-05-20 | v1.0
> 目标：让多个 Agent 围绕一个话题进行多轮交流讨论，最终产出结论

---

## 一、功能定义

### 1.1 解决什么问题

当前 Hermes 多 Agent 协作模式是**单向的**：协调者派任务 → 工作者执行 → 汇报结果。缺少一个**多向讨论**的机制，让多个 Agent 能够：

- 围绕一个开放性话题**交换观点**
- **回应彼此**的发言，而非只对协调者汇报
- 在多轮碰撞中**收敛共识**，产出结论

**核心价值**：把「一个人干活汇报」变成「一群人开会讨论」。

### 1.2 典型场景

| 场景 | 参与者 | 产出 |
|------|--------|------|
| 技术方案评审 | 产品、前端、后端、架构 | 技术方案共识文档 |
| 竞品分析讨论 | 产品、市场、设计 | 竞品对比结论 |
| Bug 根因分析 | 后端、运维、测试 | 根因定位 + 修复方案 |
| 产品需求讨论 | 产品、设计、开发 | PRD 共识 |
| 架构决策 | 架构师、后端、前端、DevOps | ADR (Architecture Decision Record) |

---

## 二、用户故事

### 2.1 协调者（发起人）

> 作为协调者，我希望发起一个圆桌讨论，指定话题和参与者，让多个 Agent 自由发言讨论，最终自动产出结论文档。

**流程**：
1. 我说：「开个圆桌讨论，话题是 XXX，让产品、设计、开发都参加」
2. 系统自动邀请指定 Agent 加入讨论
3. 每个 Agent 轮流发言，可以看到前面所有人的发言
4. 讨论进行 N 轮后，系统自动总结共识和分歧
5. 产出一份结论文档，包含：共识点、分歧点、待办事项

### 2.2 参与 Agent

> 作为参与讨论的 Agent，我希望看到其他人的发言并做出回应，而不是只对协调者汇报。

**体验**：
- 我能看到完整的讨论历史（谁说了什么）
- 我可以引用或回应其他人的观点
- 我的角色影响我的视角（产品关注用户体验，开发关注可行性）
- 讨论结束后，我的观点被纳入结论文档

---

## 三、讨论流程设计

### 3.1 完整生命周期

```
发起(Initiate)
   │
   ▼
邀请(Invite) ──→ 参与者确认加入
   │
   ▼
开场白(Round 0) ──→ 协调者陈述话题背景
   │
   ▼
┌──────────────────────────────┐
│  多轮讨论 (Round 1..N)        │
│                              │
│  每轮：                       │
│  1. 按顺序每个参与者发言       │
│  2. 可引用/回应之前的发言      │
│  3. 每轮结束自动检查收敛度     │
│                              │
│  终止条件：                    │
│  - 达到最大轮次（默认 5 轮）   │
│  - 参与者投票结束              │
│  - 协调者手动终止              │
│  - 收敛度达标（共识率 > 80%）  │
└──────────────────────────────┘
   │
   ▼
总结(Summarize) ──→ 自动生成结论文档
   │
   ▼
产出(Deliver) ──→ 保存到指定位置
```

### 3.2 发言格式

每条发言包含：
```
发言ID | 角色 | 时间 | 内容 | 引用(可选)
```

示例：
```
[#3] 产品(饼哥) | Round 2 | 引用 #1(码飞)
  我同意码飞说的技术可行性，但从产品角度来说，
  用户要的不是钻头，是墙上的洞。我们应该优先考虑用户体验。
```

### 3.3 收敛度评估

每轮结束后，系统自动评估讨论收敛度：
- **共识点**：多个参与者认同的观点
- **分歧点**：参与者意见不同的地方
- **新增点**：本轮新提出的话题

收敛度公式：`共识点数 / (共识点数 + 分歧点数)`

当收敛度 > 80% 或达到最大轮次时，进入总结阶段。

---

## 四、交互模型

### 4.1 Agent 间可见性

**核心要求**：每个参与 Agent 必须能看到完整的讨论历史。

```
Round 1:
  Agent A: "我认为应该用 React"
  Agent B: "Vue 更适合我们团队"     ← Agent C 能看到这条
  Agent C: "综合来看，React 生态更好" ← A 和 B 能看到这条

Round 2:
  Agent A: "听了 B 和 C 的观点后..."  ← 引用 Round 1 的发言
```

### 4.2 发言顺序策略

| 策略 | 说明 | 适用场景 |
|------|------|----------|
| 固定顺序 | 按邀请顺序轮流 | 正式评审 |
| 随机顺序 | 每轮随机打乱 | 头脑风暴 |
| 优先级顺序 | 按角色重要性排序 | 决策会议 |
| 自由发言 | 谁先准备好谁说 | 非正式讨论 |

默认使用**固定顺序**，可通过参数配置。

### 4.3 发言轮次控制

- **最少轮次**：2 轮（确保有回应机会）
- **默认最大轮次**：5 轮
- **可配置**：发起时可指定 `max_rounds`
- **提前终止**：协调者可随时终止，或参与者投票终止

---

## 五、技术路径评估

### 5.1 方案 A：扩展现有 Kanban 评论系统

**思路**：在 kanban task 的 comment 系统上增加回复引用、参与者管理、轮次标记。

**优点**：
- 复用现有 SQLite 存储，无需新建数据库
- kanban 已有 task/comment 基础设施
- 与现有工作流自然集成

**缺点**：
- kanban 设计初衷是**任务管理**，不是讨论
- 评论系统是**单向追加**，没有回复/引用结构
- 需要大幅修改 kanban schema（加 participant、round、reply_to 字段）
- 破坏 kanban 的简洁性，增加维护负担
- 讨论逻辑（轮次控制、收敛评估）不适合放在 kanban 里

**改造量估算**：
- schema 变更：4 个新字段，2 个新表
- 新增工具：roundtable_init, roundtable_speak, roundtable_summarize
- 代码改动：~800 行 Python
- 测试：~200 行

**风险**：
- 高。改动 kanban 核心 schema 可能影响现有功能
- 讨论和任务管理混在一起，概念混乱

### 5.2 方案 B：新建独立 Roundtable Skill（推荐）

**思路**：创建一个独立的 roundtable skill，有自己的数据模型和工具集，可以复用 kanban 的存储层但不侵入其 schema。

**优点**：
- 关注点分离：任务管理 vs 讨论交流
- 可以设计最优的数据模型（专门针对讨论场景）
- 不影响现有 kanban 功能
- 作为 skill 可以独立演进、独立发布
- 符合 Hermes 的 skill 扩展哲学

**缺点**：
- 需要新建一套工具和数据模型
- 与 kanban 的集成需要额外设计

**实现量估算**：
- 新建 skill 文档 + 工具：~600 行 Python
- 数据模型：独立 SQLite 表或 JSON 文件
- 测试：~150 行

**风险**：
- 低。完全独立，不影响现有系统
- 可以渐进式实现，MVP 先跑起来

### 5.3 对比总结

| 维度 | 方案 A (kanban 扩展) | 方案 B (独立 skill) |
|------|---------------------|-------------------|
| 实现复杂度 | 高（改核心 schema） | 中（新建独立模块） |
| 对现有系统影响 | 高 | 无 |
| 概念清晰度 | 混乱（任务+讨论） | 清晰（职责分离） |
| 可扩展性 | 受限于 kanban 设计 | 自由设计 |
| 维护成本 | 高（耦合） | 低（独立） |
| 用户学习成本 | 低（熟悉 kanban） | 中（新概念） |
| **推荐** | ❌ | ✅ **推荐** |

### 5.4 推荐方案：方案 B

**理由**：
1. 讨论和任务是两个不同的概念，混在一起会两头不讨好
2. kanban 的简洁性是它的核心优势，不应该被破坏
3. 独立 skill 可以更好地优化讨论体验
4. 可以复用 kanban 的存储基础设施（SQLite），但不侵入其 schema

---

## 六、产品设计（基于方案 B）

### 6.1 核心概念

| 概念 | 说明 |
|------|------|
| Roundtable | 一次圆桌讨论的实例 |
| Topic | 讨论话题 |
| Participant | 参与者（Agent profile） |
| Round | 一轮发言 |
| Speech | 一条发言 |
| Consensus | 共识点 |
| Disagreement | 分歧点 |
| Conclusion | 最终结论文档 |

### 6.2 工具集设计

```
roundtable_init(topic, participants, options)
  → 创建讨论，返回 discussion_id

roundtable_join(discussion_id, participant)
  → 参与者加入讨论

roundtable_speak(discussion_id, participant, content, reply_to?)
  → 发言（可选引用其他发言）

roundtable_read(discussion_id, since_round?)
  → 读取讨论历史

roundtable_status(discussion_id)
  → 查看讨论状态（当前轮次、收敛度）

roundtable_summarize(discussion_id)
  → 生成结论文档

roundtable_end(discussion_id)
  → 结束讨论
```

### 6.3 数据模型

```sql
-- 讨论主表
CREATE TABLE roundtables (
    id TEXT PRIMARY KEY,
    topic TEXT NOT NULL,
    status TEXT DEFAULT 'active',  -- active, concluded, cancelled
    max_rounds INTEGER DEFAULT 5,
    current_round INTEGER DEFAULT 0,
    created_by TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    concluded_at INTEGER,
    conclusion TEXT  -- 最终结论文档
);

-- 参与者表
CREATE TABLE roundtable_participants (
    discussion_id TEXT NOT NULL,
    participant TEXT NOT NULL,  -- profile name
    role TEXT,  -- 角色描述，如"产品总监"
    joined_at INTEGER NOT NULL,
    PRIMARY KEY (discussion_id, participant),
    FOREIGN KEY (discussion_id) REFERENCES roundtables(id)
);

-- 发言表
CREATE TABLE roundtable_speeches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    discussion_id TEXT NOT NULL,
    round INTEGER NOT NULL,
    participant TEXT NOT NULL,
    content TEXT NOT NULL,
    reply_to INTEGER,  -- 引用的发言 ID
    created_at INTEGER NOT NULL,
    FOREIGN KEY (discussion_id) REFERENCES roundtables(id),
    FOREIGN KEY (reply_to) REFERENCES roundtable_speeches(id)
);

-- 共识/分歧记录
CREATE TABLE roundtable_findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    discussion_id TEXT NOT NULL,
    type TEXT NOT NULL,  -- 'consensus', 'disagreement', 'new_point'
    content TEXT NOT NULL,
    round INTEGER NOT NULL,
    FOREIGN KEY (discussion_id) REFERENCES roundtables(id)
);
```

### 6.4 发起方式

**方式 1：通过协调者发起**
```
用户: "开个圆桌讨论，话题是数据库选型，让后端、架构、运维参加"
协调者: 调用 roundtable_init(...)
       → 自动创建讨论并邀请参与者
       → 启动多轮讨论流程
```

**方式 2：通过 CLI 发起**
```bash
hermes roundtable start \
  --topic "数据库选型" \
  --participants "backend,architect,devops" \
  --max-rounds 5
```

**方式 3：通过 kanban 任务触发**
```
kanban task 标记 skills: ["roundtable"]
→ 调度器识别后，用 roundtable 模式执行
```

### 6.5 与现有系统集成

```
                    ┌─────────────┐
                    │   用户/协调者  │
                    └──────┬──────┘
                           │ 发起讨论
                           ▼
                    ┌─────────────┐
                    │  Roundtable  │ ← 独立 skill
                    │    Skill     │
                    └──────┬──────┘
                           │
          ┌────────────────┼────────────────┐
          │                │                │
          ▼                ▼                ▼
    ┌───────────┐    ┌───────────┐    ┌───────────┐
    │  Agent A   │    │  Agent B   │    │  Agent C   │
    │ (产品)     │    │ (设计)     │    │ (开发)     │
    └─────┬─────┘    └─────┬─────┘    └─────┬─────┘
          │                │                │
          └────────────────┼────────────────┘
                           │ 通过 kanban/消息 交换发言
                           ▼
                    ┌─────────────┐
                    │   结论文档    │
                    └─────────────┘
```

集成点：
1. **Kanban 集成**：讨论可以关联到 kanban task，讨论结果作为 task 的 comment
2. **飞书集成**：讨论过程可以实时同步到飞书群
3. **Session 集成**：每个参与 Agent 的发言记录到其 session history

---

## 七、产出物定义

### 7.1 结论文档格式

```markdown
# 圆桌讨论结论：[话题]

## 讨论概要
- 参与者：产品(饼哥)、设计(像素姐)、开发(码飞)
- 轮次：3 轮
- 时间：2026-05-20 14:00 - 14:30

## 共识点
1. [共识1]
2. [共识2]

## 分歧点
1. [分歧1] - 各方观点
2. [分歧2] - 各方观点

## 待办事项
1. [ ] [待办1] - 负责人：xxx
2. [ ] [待办2] - 负责人：xxx

## 详细发言记录
### Round 1
- **产品(饼哥)**: ...
- **设计(像素姐)**: ...
- **开发(码飞)**: ...

### Round 2
...
```

### 7.2 产出物存储位置

- 默认：`/Users/parsifal/Repo/Monorepo/<project>/docs/product/roundtable-<topic>.md`
- 可配置：发起时指定输出路径
- 自动关联：保存到关联的 kanban task comment 中

---

## 八、验收标准

### 8.1 功能验收

| # | 验收项 | 验收标准 | 优先级 |
|---|--------|----------|--------|
| 1 | 发起讨论 | 能创建讨论、指定话题和参与者 | P0 |
| 2 | 多轮发言 | 参与者能轮流发言，至少 3 轮 | P0 |
| 3 | 发言可见性 | 每个参与者能看到所有历史发言 | P0 |
| 4 | 引用回复 | 能引用并回应其他参与者的发言 | P1 |
| 5 | 自动总结 | 讨论结束后自动生成结论文档 | P0 |
| 6 | 收敛检测 | 能检测讨论收敛度并决定是否继续 | P1 |
| 7 | 提前终止 | 协调者能提前终止讨论 | P1 |
| 8 | 飞书同步 | 讨论过程同步到飞书群 | P2 |
| 9 | CLI 支持 | 通过 CLI 发起和管理讨论 | P2 |
| 10 | 并行讨论 | 支持同时进行多个独立讨论 | P2 |

### 8.2 性能验收

| 指标 | 目标 |
|------|------|
| 单轮发言延迟 | < 30s（包含 LLM 调用） |
| 结论文档生成 | < 60s |
| 并发讨论数 | ≥ 3 |
| 历史发言查询 | < 1s |

---

## 九、优先级划分

### P0 - 核心功能（MVP）

- [ ] 创建独立 roundtable skill
- [ ] 实现 roundtable_init / speak / read / summarize 工具
- [ ] SQLite 数据模型
- [ ] 多轮发言流程控制
- [ ] 自动结论文档生成
- [ ] 基本的协调者发起流程

### P1 - 增强功能

- [ ] 引用回复支持
- [ ] 收敛度检测算法
- [ ] 提前终止机制
- [ ] 发言顺序策略配置
- [ ] 与 kanban task 关联

### P2 - 扩展功能

- [ ] 飞书群实时同步
- [ ] CLI 命令行支持
- [ ] 并行讨论管理
- [ ] 讨论模板（技术评审、需求讨论等）
- [ ] 历史讨论搜索和回顾

---

## 十、实现路线图

### Phase 1：MVP（1 周）

```
Day 1-2: 数据模型 + 基础工具
  - roundtable_init / speak / read
  - SQLite schema

Day 3-4: 讨论流程控制
  - 轮次管理
  - 参与者顺序
  - 状态管理

Day 5: 总结生成
  - roundtable_summarize
  - 结论文档模板

Day 6-7: 测试 + 集成
  - 单元测试
  - 端到端测试
  - 文档编写
```

### Phase 2：增强（1 周）

- 引用回复
- 收敛检测
- 提前终止
- kanban 集成

### Phase 3：扩展（1 周）

- 飞书同步
- CLI 支持
- 讨论模板
- 性能优化

---

## 十一、开放问题

1. **发言 token 限制**：每个 Agent 每轮发言的 token 上限是多少？建议 500-1000 tokens。
2. **并行 vs 串行发言**：每轮内各参与者是串行发言（A说完B再说）还是可以并行？建议串行，确保能看到前面的发言。
3. **讨论记录保留**：讨论历史是否永久保存？建议保存到项目目录，可选同步到飞书。
4. **权限控制**：是否需要限制谁能发起讨论？建议初期不限制，后续按需添加。

---

## 十二、总结

圆桌讨论功能是 Hermes 多 Agent 协作的重要补充，让 Agent 从「单向汇报」进化到「多向讨论」。

**推荐方案**：新建独立 roundtable skill（方案 B），理由：
1. 概念清晰，职责分离
2. 不影响现有 kanban 系统
3. 可以设计最优的讨论数据模型
4. 渐进式实现，MVP 先跑起来

**下一步**：
1. 确认方案选择
2. 创建 roundtable skill 骨架
3. 实现 MVP
4. 内部试用 + 迭代

---

*饼哥说：用户要的不是钻头，是墙上的洞。圆桌讨论要的不是消息队列，是共识。*
