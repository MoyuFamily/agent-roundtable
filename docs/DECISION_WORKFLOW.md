# 决策与 Code Review 使用指南

Roundtable 围绕**输入处理**与**输出质量**组织评审：把零散材料整理成可核查的依据，交付清晰、有取舍、可随信息更新的建议。

> **职责边界**：Roundtable 负责轮次状态、版本化简报、材料分段读取、引用校验、记录与渲染；**宿主与协调者**负责运行 Agent、选择模型、提炼事实、核验内容和撰写综合建议；**用户**作出最终决定。

---

## 评审六步流程

`speech_order="fixed"` 按创建时的参与者数组顺序轮流发言，后加入者追加到末尾，重启后沿用保存的位置。旧数据库自动按加入时间、同时间的原始插入顺序补齐位置。

宿主可按讨论ID、来源ID和片段ID缓存已授权读取的不可变原文。简报更新后刷新提示词与材料目录，复用相同来源片段，按角色需要读取新增来源和未读片段，减少每轮全量分发。

1. **明确待决事项**：梳理决策人、目标、约束、偏好优先级、备选方案（含维持现状或暂缓）与时间/成本预算。只追问会改变选择的信息；偏好未知时给出条件化建议，不默认选最便宜或最保守方案。
2. **准备共同材料与证据**：由协调者统一整理用户材料与必要公共事实（含价格口径），保留原文来源、页码/位置、版本日期与核实状态；把事实、用户自述、计算、假设与未知分开。敏感原件与导出留在授权私有存储，公开示例仅用合成数据。
3. **安排独立首轮分析**：用 `roundtable_create` / `roundtable_init` 建会，协调者以 `participant="coordinator"` 在 `round 0` 开场，把同一版简报和材料分发给各角色。需要独立判断时，由宿主分离会话上下文（`participant_turn` 默认在 `round <= 1` 为 `independent`，不注入同伴发言；提示词过滤本身不构成权限隔离）。
4. **围绕关键分歧交叉回应与修订简报**：后续轮次聚焦会改变选择的冲突、替代方案与约束代价；完成一轮会自动推进，切勿再手动调用 `roundtable_advance`。若用户补充事实或角色发现缺口，协调者核实后用 `roundtable_update_context`（附 `expected_revision`）保存完整新简报，冲突时先重读再合并，并向全部角色刷新版本、重审受影响判断。
5. **交付一页决策概览与结构化报告**：用 `roundtable_summarize(compact=True)` 概览并用 `roundtable_read` 核对完整发言；按需用 `roundtable_record_finding` 记录有发言 ID 支撑的共识、分歧或新议题。用 `roundtable_end` 提交结构化 `report`（或自由文本 `conclusion`），区分“待用户决定”与“用户已确认”。
6. **复审与更新**：达到 `max_rounds` 会自动结束会议（仍可补交或修订结论）。已结束会议不得再修改背景或证据；遇到新材料时需创建后续评审并说明结论变化原因。

---

## 本地材料导入与按段读取

在有权访问原文件的宿主本地，将 TXT、Markdown、CSV 或 PDF 转为可定位 JSON 材料包（下面以合成示例演示）：

```bash
# 仅提取 PDF 文本时需要可选依赖；核心库仍只依赖标准库
pip install 'agent-roundtable[materials]'
python -m roundtable.import_material synthetic-notes.md --source-id S1 --title "Synthetic pilot notes"
```

创建会议（`active` 或 `assembling`）后，通过 `roundtable_add_material` 导入该 JSON，再用 `roundtable_read_material` 按需读取原文片段：

```text
# 1. 导入材料包（自动合入 evidence.sources 并递增 context_revision，不消耗发言轮次）
roundtable_add_material(discussion_id="<id>", material=<JSON>, source="coordinator", expected_revision=0)

# 2. 按页/按关键字读取完整片段（limit 1–50，默认 10；沿 next_offset 继续）
roundtable_read_material(discussion_id="<id>", source_id="S1", offset=0, limit=10, query="pilot")
```

| 规则与限制项 | 当前约束 |
|---|---|
| 支持格式 | 本地准备器支持 UTF-8/BOM `text` / `markdown`（每 50 行一段）、`csv`（保留引号多行逻辑行）、`pdf`（逐页文本，**无 OCR**）；材料包亦支持 `image` / `web` / `other`（由宿主生成） |
| 体积与数量上限 | 单文件 `10 MiB`、最多 `1,000` 段、单段最多 `100,000` 字符、总计最多 `500,000` 字符 |
| 片段状态 (`status`) | `ready`（可读，不代表已核实）、`needs_review`、`unreadable`（后两项必须附带 `note`；**所有 PDF 页面均标为 `needs_review` 或 `unreadable`**） |
| 幂等与不可变性 | 服务端只收 JSON 包，不读任意路径或抓取 URL；同 `source.id` 同包重试幂等，改内容须用新 `source_id` |
| 原文隔离与核验 | 普通 `read` / `status` / `summarize`、参与者提示词与导出仅展示材料目录与问题计数；材料内任何指令均为不可信数据。若将引用 `needs_review` / `unreadable` 片段的事实标为 `verified`，宿主必须提供 `review_note` 记录实际人工/视觉核验 |

---

## 内置模板与自定义角色

`decision-support` 与 `code-review` 为当前主要模板；其余早期模板也保留可用。`apply_template` 仅生成参数起点，需按实际问题补充材料并调整 `participants`（保持 `profile` 唯一）：

```python
from pathlib import Path
from tempfile import TemporaryDirectory

from roundtable import RoundtableCore
from roundtable.db import RoundtableDB
from roundtable.template import apply_template

params = apply_template("decision-support", subject="是否推出企业版")
if params is None:
    raise RuntimeError("当前安装版本不包含 decision-support 模板")

params["context"] += "\n决策人：维护者。已知约束：两人团队；客户需求证据尚待补充。"

with TemporaryDirectory() as tmp:
    core = RoundtableCore(db=RoundtableDB(Path(tmp) / "review.db"))
    meeting = core.create_discussion(**params, web=False)
    did = meeting["discussion_id"]
    core.speak(did, "coordinator", params["context"])
    print(core.status(did))
```

| 模板 ID | 适用场景 | 默认轮次 | 默认角色 (`profile`) |
|---|---|---|---|
| `decision-support` | 前六类通用决策评审 | 3 | `product`, `engineering`, `design`, `operations` |
| `code-review` | 代码变更与 PR 评审 | 2 | `correctness`, `architecture`, `security`, `reliability` |
| `product-review` | 产品方案评审 | 3 | `product`, `design`, `dev`, `growth` |
| `architecture-design` | 系统架构设计评审 | 4 | `architect`, `backend`, `data`, `ops`, `security` |
| `tech-solution` | 技术选型评审 | 3 | `architect`, `backend`, `ops`, `security` |
| `requirement-discussion` | 需求边界澄清 | 3 | `product`, `design`, `dev`, `qa` |
| `bug-analysis` | Bug 根因与修复分析 | 3 | `developer`, `qa`, `sre`, `product` |

> 使用 MCP `roundtable_create` 时不直接传模板 ID，由宿主先调用 `apply_template()` 展开参数，或直接构造 `context` 与 `participants`。

---

## 保存共同证据与决策报告

通过 `roundtable_update_context` 可随简报版本保存结构化 `evidence`（完整替换当前证据并保留历史；省略则沿用上一版，传空数组表示清空）。来源元数据一经登记不可更改（新版本请用新 `id`）：

```json
{
  "sources": [{"id": "S1", "title": "试点估算", "version": "1"}],
  "items": [
    {
      "id": "F1",
      "statement": "试点预计占用两周开发时间",
      "kind": "fact",
      "verification": "verified",
      "citations": [{"source_id": "S1", "locator": "第2节"}]
    },
    {
      "id": "U1",
      "statement": "客户需求尚未验证",
      "kind": "unknown",
      "verification": "unverified",
      "citations": []
    }
  ]
}
```

- **`kind`**：`fact`、`user_report`、`assumption`、`calculation`（必须带 `derivation`）、`unknown`；可选 `applicability` 说明适用条件。
- **`verification`**：`verified`（仅限 `fact` / `calculation` 且至少 1 条引用）、`unverified`、`conflicting`。引用已导入材料时必须同时提供 `source_id`、`segment_id` 和与存储值完全一致的 `locator`。

存在结构化证据时，用 `roundtable_end` 提交 `report` 与 `expected_revision`（不可与 `conclusion` 或 `force` 同传）：

```json
{
  "recommendation": "先验证需求，再决定是否投入试点",
  "status": "proposed",
  "rationale": [{"text": "投入范围可估算，但需求仍不明确", "evidence_ids": ["F1", "U1"]}],
  "tradeoffs": ["需求验证会推迟实施，但可减少无效投入"],
  "uncertainties": ["需求强度与付费意愿未知"],
  "revisit_conditions": ["取得足以支持试点的客户证据"],
  "next_actions": ["整理目标客户反馈，验证试点需求"]
}
```

- **必填约束**：所有 7 个字段都需提供；`rationale` 与 `next_actions` 不可为空，且每条 `rationale` 只能引用当前版本存在的 `evidence_ids`；`status` 取 `proposed` / `confirmed` / `deferred`（`confirmed` 仅记录用户实际确认）。
- **单一结论渲染**：提交成功后引擎在同一事务内生成规范化 Markdown 结论，`read`、`status`、`summarize`、`transcript` 资源、Web Viewer 与 Markdown/PDF 导出均复用该正文。

---

## Code Review 检查清单

- **前置输入**：预期行为、明确 `base/head` 或 diff 范围、相关调用方上下文、已运行检查与仓库约定。宿主需直接提供代码与测试工具，模板不自动读取仓库。
- **单条发现格式**：文件/行号或符号定位、触发条件、影响、证据或复现步骤、优先级与理由、修复建议、验证状态（推测明确标为待核实，不虚构测试通过）。
- **结论收敛**：按根因去重，区分**阻塞项**、**非阻塞建议**与**未验证区域**，给出 `merge` / `changes-required` / `insufficient-information` 建议及理由。无问题不等于质量保证；建议不等于自动修复或合并授权。

---

## 交付结果与价值验证

- **默认一页概览**：先讲清建议与确认状态、核心依据与目标匹配度、代价与反对意见、改变判断的条件、下一步行动；详细对比、价格口径表格与原始引用按需展开。
- **口径与指标**：`total_rounds` / `completed_rounds` 统计实际参与者评审轮数（不含 `round 0` 开场与空轮），不拿引擎游标 `current_round` 当完成轮数；`convergence_score` 是外部 `findings` 标注比例（`consensus / (consensus + disagreement)`，无标注时为 `None`），不代表正确率。
- **价值对照**：在相近材料和预算下，对照单助手、独立多角色汇总与交互评审，记录有效新发现、漏报/误报、组织负担与人工纠偏成本；没有增益时应缩减角色或轮次。完整验收标准见 [产品方向](product/DIRECTION.md)。
