# 圆桌讨论功能 — 产品验收报告

> 验收人：饼哥（产品总监）| 日期：2026-05-20
> PRD：docs/product/PRD.md v1.0
> 测试报告：docs/TEST-RESULTS.md
> 代码：src/hermes_cli/roundtable_db.py + src/tools/roundtable_tools.py + src/skills/SKILL.md

---

## 一、验收结论

### ✅ 有条件通过

**核心功能完整度 90%，1 个阻塞性 Bug 修复中，2 个改进建议。**

MVP 核心流程（创建 → 发言 → 轮次推进 → 收敛检测 → 总结 → 结束）运行正确，
85/87 测试通过。BUG-1（coordinator 发言被拒绝）已派给码飞修复（t_e411e82e），
修复后即可完整走通 Skill 文档描述的协调者流程。

---

## 二、功能对照表（PRD 需求 vs 实际实现）

### P0 核心功能

| # | PRD 需求 | 实现状态 | 说明 |
|---|----------|----------|------|
| 1 | 创建讨论 + 指定话题和参与者 | ✅ 已实现 | `roundtable_init`，ID 格式 `rt_xxxxxxxx`，支持 topic/context/max_rounds/speech_order/output_path |
| 2 | 多轮发言（至少 3 轮） | ✅ 已实现 | `roundtable_speak`，轮次自动推进，全部参与者发言后 advance |
| 3 | 发言可见性（参与者互相可见） | ✅ 已实现 | `roundtable_read` 返回完整历史，支持 formatted_history 格式化输出 |
| 4 | 自动总结生成结论文档 | ✅ 已实现 | `roundtable_summarize` 返回结构化数据（topic/participants/rounds/speech_count/consensus/disagreement），由 coordinator agent 生成 Markdown |
| 5 | 独立 roundtable skill（方案 B） | ✅ 已实现 | 独立 SQLite 数据库 `roundtable.db`，不侵入 kanban schema |
| 6 | SQLite 数据模型 | ✅ 已实现 | 5 张表：discussions, participants, speeches, findings, convergence_history（比 PRD 多 1 张 convergence_history） |
| 7 | 工具集设计 | ✅ 已实现 | 7 个工具（比 PRD 多 1 个 `roundtable_list`）：init, speak, read, status, summarize, end, list |
| 8 | 协调者发起流程 | ⚠️ 部分实现 | 创建讨论 ✅，但 coordinator 开场白被拒绝（BUG-1），修复中 |

### P1 增强功能

| # | PRD 需求 | 实现状态 | 说明 |
|---|----------|----------|------|
| 9 | 引用回复支持 | ✅ 已实现 | `reply_to` 参数，跨发言引用正确保存和读取 |
| 10 | 收敛度检测算法 | ✅ 已实现 | `convergence_history` 表 + `record_convergence` 方法，公式：consensus / (consensus + disagreement) |
| 11 | 提前终止机制 | ⚠️ 部分实现 | 协调者手动终止 ✅（`roundtable_end(force=true)`），参与者投票终止 ❌ 未实现 |
| 12 | 发言顺序策略配置 | ⚠️ 部分实现 | schema 支持 fixed/random/priority/free，但实际只实现 fixed 顺序逻辑 |
| 13 | 与 kanban task 关联 | ⚠️ 部分实现 | Skill 文档描述了 kanban_comment 关联方式，但无自动化集成 |

### P2 扩展功能

| # | PRD 需求 | 实现状态 | 说明 |
|---|----------|----------|------|
| 14 | 飞书群实时同步 | ❌ 未实现 | Phase 3 规划 |
| 15 | CLI 命令行支持 | ❌ 未实现 | Phase 3 规划 |
| 16 | 并行讨论管理 | ✅ 已实现 | 独立数据库天然支持多讨论并行 |
| 17 | 讨论模板 | ❌ 未实现 | Phase 3 规划 |
| 18 | 历史讨论搜索 | ⚠️ 部分实现 | `roundtable_list` 支持状态过滤，但无全文搜索 |

---

## 三、发现的问题清单

### BUG-1：Coordinator 无法通过工具层发言（阻塞）

- **严重程度**：高
- **状态**：修复中（t_e411e82e，码飞负责）
- **影响**：Skill 文档 Step 2（coordinator opening statement）无法执行
- **根因**：`_handle_speak` 校验 `participant in get_active_participant_names()`，但 coordinator 不在 participants 表中
- **建议修复**：当 `participant == "coordinator"` 时跳过参与者校验，且 coordinator 发言不计入轮次推进

### IMPROVE-1：DB 层单参与者校验缺失

- **严重程度**：低
- **现状**：DB 层 `create_discussion` 允许 < 2 participants，工具层有约束
- **建议**：DB 层也应校验至少 2 个参与者，与工具层保持一致

### IMPROVE-2：speech_order 参数文档不完整

- **严重程度**：低
- **现状**：`create_discussion` 接受 `speech_order` 参数（fixed/random/priority/free），但只实现了 fixed 顺序
- **建议**：文档说明其他选项的实现状态或计划时间表

---

## 四、各维度评价

### 1. 功能完整性 — ⭐⭐⭐⭐ (4/5)

**亮点**：
- 7 个工具覆盖了讨论的完整生命周期
- 数据模型设计合理，5 张表职责清晰
- 独立数据库方案干净利落，不污染 kanban

**不足**：
- coordinator 发言 Bug 阻塞了完整流程验证
- 部分 P1/P2 功能未实现（投票终止、random/priority 顺序）

### 2. 用户体验 — ⭐⭐⭐⭐ (4/5)

**亮点**：
- `formatted_history` 输出人类可读的讨论记录，格式清晰
- `next_speaker` 提示让 coordinator 知道下一步该谁发言
- 讨论结束后的 summarize 数据结构化程度高，方便生成结论文档
- Skill 文档的 Participant Prompt Template 设计贴心

**不足**：
- 缺少用户可见的进度指示（如 "Round 2/5, 进度 60%"）
- 结论文档需要 coordinator agent 手动写入，没有自动文件输出

### 3. 产出物质量 — ⭐⭐⭐⭐ (4/5)

**亮点**：
- summarize 返回的数据包含：topic、participants、rounds、speech_count、consensus_points、disagreement_points、convergence_history
- 结论文档模板在 Skill 文档中有明确定义
- 支持 output_path 配置

**不足**：
- 结论文档的自动生成是"返回数据 + coordinator 写入"模式，没有一键输出 Markdown 文件
- 缺少待办事项（Action Items）的结构化支持

### 4. 边界场景处理 — ⭐⭐⭐⭐ (4/5)

**亮点**：
- 发言冲突：结束后拒绝新发言 ✅
- 超时：达到 max_rounds 自动结束 ✅
- 无人发言：轮次推进逻辑正确（全部发言后才 advance）✅
- 重复参与者：DB 层拒绝同名 profile ✅
- 引用不存在的发言：抛 ValueError ✅

**不足**：
- 单参与者场景：DB 层允许，工具层拒绝，逻辑不一致
- 二次结束：DB 层返回 False 不抛异常，行为不直观

### 5. 可复用性 — ⭐⭐⭐⭐⭐ (5/5)

**亮点**：
- 作为独立 skill，其他用户 `toolsets: [roundtable]` 即可启用
- 数据库路径支持环境变量 `HERMES_ROUNDTABLE_DB` 覆盖
- 工具 schema 定义规范，参数描述清晰
- 与现有系统零耦合，不影响 kanban 和其他功能

---

## 五、改进建议

### 短期（本次迭代收尾）

1. **修复 BUG-1**：coordinator 发言支持，确保完整流程可跑通
2. **DB 层参与者校验**：`create_discussion` 增加 `len(participants) >= 2` 检查
3. **speech_order 文档**：标注哪些策略已实现、哪些是 placeholder

### 中期（Phase 2）

4. **投票终止**：实现参与者投票结束讨论的机制
5. **random/priority 发言顺序**：补齐 speech_order 策略实现
6. **自动文件输出**：`roundtable_summarize` 增加可选的 Markdown 文件写入
7. **进度指示**：在 `roundtable_status` 返回中增加进度百分比

### 长期（Phase 3）

8. **飞书同步**：讨论过程实时同步到飞书群
9. **CLI 支持**：`hermes roundtable start` 命令
10. **讨论模板**：技术评审、需求讨论等预设模板
11. **全文搜索**：历史讨论内容检索

---

## 六、总体评价

圆桌讨论功能作为 MVP 交付质量**良好**。

从产品角度来说，核心价值已经验证：多个 Agent 确实能围绕一个话题进行多轮交流，系统能正确跟踪轮次、检测收敛、生成结论数据。独立 skill 的架构选择是正确的——干净、可扩展、零耦合。

测试覆盖扎实（85/87 通过），DB 层 45 个测试全绿，工具层 26 个 E2E 全绿，边缘场景 14/16 通过（2 个是设计备注，非缺陷）。

BUG-1 是唯一的阻塞项，修复成本低（一行代码），不阻塞整体验收结论。

**一句话**：MVP 跑通了，骨架搭好了，接下来是长肉的阶段。

---

*饼哥说：用户要的不是钻头，是墙上的洞。圆桌讨论要的不是消息队列，是共识。目前共识机制已就位，下一步是让共识更容易达成。*
