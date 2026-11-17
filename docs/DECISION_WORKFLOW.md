# 决策与 Code Review 使用指南

这套流程围绕输入处理和输出质量：把用户材料整理成可检查的依据，交付清晰、有取舍、可行动的建议。多角色分析用于补足重要遗漏或核实争议，按实际贡献决定规模。

当前由宿主运行 Agent、解析材料、核验并撰写结果，Roundtable 记录会议并提供提示词。角色定义专业责任，Agent 携带资料与工具，模型按具体任务选择。已有记录与结论支持 Markdown 导出及 PDF 排版渲染（需可用浏览器）；自动解析、模型选择、自动组队、证据验证、分析图表生成与跨产物一致性检查尚未由引擎实现。

## 何时使用

适合项目去留与方向、产品范围与优先级、技术路线、发布与实施、资源与商业模式、工作流程与工具选择，以及 Code Review。七类场景并列，实际验证可分批开展。选择涉及多个专业约束，并影响资源、后续路径或返工成本时，可以采用这套流程。简单查询或容易撤销的小改动可以缩减为单角色分析。

各场景的问题、建议角色与交付物见 [场景清单](product/DIRECTION.md#场景清单)。当前提供通用评审流程和部分专用模板，不代表七类均已完成自动化及效果验收。

## 准备材料

先形成一份简报：待决定事项、决策人、目标、约束、偏好及优先级、备选方案、资料来源、未知信息和预算。只追问会影响选择的信息；偏好未知时给出条件化建议，不默认用户一定追求最低成本或最低风险。

主持人统一整理用户材料并补充必要的公共信息，包括价格。使用宿主可用的阅读工具提炼与决定有关的内容，保留原文核查入口，不要求用户先把所有资料手工转成表格：

- 每个来源版本有稳定 ID，注明页码/段落/表格、版本或日期、适用方案和核实状态。缺失的元信息标为未知。
- 事实、用户自述、计算、假设与未知分开；计算给出来源输入、口径和假设。报价区分实际适用价格与估算，配置、期限和费用口径不一致时不直接排名。
- 对缺页、无法读取的表格、过期资料和相互冲突的内容，说明影响与下一步核查。PDF 中影响选择的页面须渲染检查，不能因文字提取结果为空就认定内容不存在。
- 敏感原件、提取内容、来源映射、会议记录和导出放在授权的私有位置；共享范围遵循用户授权，公开示例只用合成材料。

给各角色同一版简报及授权的来源材料；角色可核查原文、质疑提炼、请求补查，公共事实仍由主持人统一补齐并分发。为每个角色明确专业问题和交付物，按预期贡献选择人数，不固定为模板中的配置。

对于 Code Review，还需明确预期行为、base/head 或 diff、相关代码上下文、已运行检查和仓库规则。宿主负责提供实际代码访问和工具；当前模板不会拉取 PR 或运行测试。

资源与商业模式需要预算、人力、成本、需求或使用量证据，区分已知数据与收入/付费假设。工作流程与工具选择需要当前流程、使用者反馈、基线耗时和候选工具的试用材料，纳入迁移、培训、维护和退出成本。不要为缺失的数据编造数值。

## 从源码使用模板

新增模板为 `decision-support` 和 `code-review`。以下代码供开发者集成验证：它创建会议并记录开场，使用临时数据库且关闭 Web；不产生实际模型调用。

```python
from pathlib import Path
from tempfile import TemporaryDirectory

from roundtable import RoundtableCore
from roundtable.db import RoundtableDB
from roundtable.template import apply_template

params = apply_template(
    "decision-support",
    subject="是否推出企业版",
)
if params is None:
    raise RuntimeError("当前安装版本不包含 decision-support 模板，请使用当前源码")

# 模板是起点：补充真实材料，按问题增删角色，保持唯一 profile。
params["context"] += "\n决策人：维护者。已知约束：两人团队；客户需求证据尚待补充。"

with TemporaryDirectory() as tmp:
    core = RoundtableCore(db=RoundtableDB(Path(tmp) / "review.db"))
    meeting = core.create_discussion(**params, web=False)
    discussion_id = meeting["discussion_id"]
    core.speak(discussion_id, "coordinator", params["context"])
    print(core.status(discussion_id))
    # 宿主接下来按角色运行 Agent，用 core.speak 记录真实返回的内容。
    # 持续使用时改为持久数据库路径；此临时示例结束后记录会被清理。
```

代码评审可替换为 `apply_template("code-review", subject="PR #123 的权限改动")`，再把真实 diff 范围、需求和验证结果补充到 context。原有产品、需求和技术模板继续可用。

前六类决策可使用 `decision-support` 并修改角色、问题和材料。通过 `apply_template(..., overrides={"participants": [...]})` 替换默认团队：每项提供唯一 `profile`、`role` 和具体 `perspective`。例如资源与商业模式安排产品、经营分析、技术、运营；工具选择安排实际使用者、技术、流程负责人。工具入口则直接传入调整后的 participants/context。创建记录不会自动选择或运行这些角色。

## Agent 工具流程

Hermes 使用 `roundtable_init`，MCP 使用 `roundtable_create`。将简报放进 `context`、各角色任务放进 participant 的 `perspective`。当前 MCP create 工具不接受模板 ID，协调者需提供相应 participants/context，或由宿主通过模板函数准备参数。

1. 创建会议，协调者以 `coordinator` 身份开场（round 0）。
2. 宿主向参与者提供共同简报、专业职责与实际工具。需要独立分析时分离上下文，首轮不注入同伴结论。
3. 根据状态返回的 next_speaker 或轮次工具依次记录发言，不假设模板列表顺序就是实际顺序；独立分析的执行可按宿主能力并行。
4. 用户补充事实或角色指出材料问题时，主持人核实并通过 `roundtable_update_context` 保存完整的新简报、实际来源和原因，传入读取到的 `context_revision` 作为 `expected_revision`。更新不占发言轮次；有冲突时重新读取，不覆盖别人刚提交的版本。向所有角色刷新共同材料，重审受影响判断；记录发言前再次核对版本，独立分析仍不注入同伴结论。
5. 根据问题覆盖、信息增益和预算决定是否继续，保留未解决分歧。完成一轮会自动推进，不要再次手动 advance。
6. 协调者核对原始材料，使用 `roundtable_record_finding` 记录有实际发言 ID 支持的共识、分歧或新议题。形成建议，使用 `roundtable_end` 的 conclusion 保存，并通过 read 或 summarize 回读核对。达到轮次上限后可以更新结论。用户尚未决定时明确标注“待用户确认”。

工具创建会议不等于启动 Agent。首轮提示词过滤不构成权限隔离；如需隔离，还必须由宿主控制会话上下文和可用工具。CodexBridge 和 GenericBridge 的 `/speak` 简写与 `/tool` 调用 `roundtable_speak` 共用处理逻辑，都会登记下一位通知。通知写入收件箱不等于宿主已经读取和执行。

`read` 与 `summarize` 返回当前 `context`、`context_revision` 和完整 `context_history`，保留旧假设和更改来源；`status` 返回当前简报及版本。已结束或取消的会议不能修改背景，需要创建后续评审，避免把旧结论套到新事实。

`total_rounds` 表示已有参与者发言的评审轮数，`completed_rounds` 表示其中引擎已经推进结束的轮数；开场、空轮和只有主持人的轮次不计入。手动提前结束的部分轮计入 total，不计入 completed。`current_round` 保持引擎游标语义，自动结束后可能为 max_rounds + 1，不应用作完成轮数。

## MCP 提示词

| 提示词 | 参数与行为 |
|---|---|
| `coordinator_kickoff` | topic、participants、可选 max_rounds/decision_brief；指导明确问题和角色任务 |
| `participant_turn` | discussion_id、role、可选 perspective/phase；包括共享 context |
| `coordinator_summarize` | discussion_id；指导比较方案、保留分歧和区分建议与决定 |

`participant_turn` 默认在 round 0–1 使用 `independent`：仅附带共享简报和协调者开场，不附带同伴发言。后续轮次默认 `response`：附带最近十条发言摘录及 ID，提醒核对完整内容。可显式传入 `phase="independent"` 或 `phase="response"`；实际阶段由宿主控制，不修改会议状态。

背景更新后，独立分析提示词使用当前简报，不再注入可能含旧假设的开场；旧开场仍保留在逐字记录。回应阶段会提醒当前简报优先于历史发言中的冲突假设。

只支持工具调用或 HTTP 的宿主，也可调用 `roundtable_get_prompt`。例如向 Bridge 的 `/tool` 发送：

```json
{
  "name": "roundtable_get_prompt",
  "arguments": {
    "name": "participant_turn",
    "arguments": {
      "discussion_id": "<会议 ID>",
      "role": "技术评审",
      "phase": "independent"
    }
  }
}
```

该工具返回提示词文本，宿主负责把它交给实际参与者，不会自行运行模型。

实际使用的模型及配置由宿主决定。不得把角色名当作模型身份，也不能把资料缺失包装成专业结论。

## 交付结果

默认先给简短的决策概览，让用户不用读会议记录也能理解：

1. 建议是什么，还是需要先验证；区分待用户决定和已确认决定。
2. 为什么：主要依据及来源，如何符合用户目标。
3. 要付出什么代价，有哪些重要反对意见或未知。
4. 哪些条件会改变建议。
5. 下一步具体做什么。

按需再展开方案对比、证据定位、计算、角色覆盖和未验证部分。影响选择的限制应在概览中可见。图表用于解释对比或变化，不能用精美排版代替核查。

短答、完整报告、表格和图文导出复用同一份已核对的事实、计算与结论；交付前核对关键数字、条件和推荐一致。材料更新后，说明哪些判断改变、为什么改变，保留未变约束，更新或标记旧产物。当前这些检查由宿主完成，简报版本历史不代表引擎已自动关联或重算所有结果。

Code Review 的每条发现包含代码位置、触发条件、影响、证据/复现、优先级理由、修复建议和验证状态。最终按根因去重，区分阻塞项、非阻塞建议、未验证部分，再给出合并、修复后再审或材料不足的建议。无问题报告不构成质量保证；评审授权不自动等于修复或合并授权。

`summarize(compact=True)` 提供格式化摘要，发言摘录带有 ID 和截断标记；已保存的结论始终完整返回。read、status、summarize 和 transcript resource 都能回读结论。配置了 output_path 时，后续 summarize 导出也保留结论。协调者仍须核对完整发言和原始资料，摘要接口不执行语义综合。

`roundtable_record_finding` 接受 finding_type（consensus、disagreement、new_point）、content、related_speeches。关联发言必须属于当前会议；完全相同内容和引用的重试不重复计数。返回的 findings 包含 ID 与来源发言，摘要保留标注来源。标注属于外部判断，工具不会自动验证，也不能由空列表推断意见一致。共识比例只描述已记录标注，不表示模型投票结果或结论正确率。

## 验证价值

先检查输入是否提取准确、来源是否可查、关键缺口是否保留，再检查结论是否有依据、符合用户目标、可行动，以及不同产物是否一致。记录用户纠正和补充材料的负担、人工整理时间和宿主补救。

在相近材料与预算下，用真实任务比较单助手、独立多角色汇总、带交互的多角色评审；条件允许时再比较同模型与异模型安排。记录有效贡献、可行方案增量、误报/重复意见、总耗时、费用和采纳原因。没有增益时减少角色或停止后续讨论。代码评审另外记录已知缺陷漏报。无法观测的指标标为未知，不用更多格式、评论、更高共识或更长报告代替效果。

完整优先级及维护决策标准见 [产品方向](product/DIRECTION.md)。
