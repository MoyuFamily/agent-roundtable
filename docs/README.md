# Roundtable 文档总览

本目录提供面向**人类用户、宿主集成者与仓库贡献者**的中文参考文档；给 **AI Agent 运行时**读取的调用规范放在仓库根目录与包内 Skill 中。

## 按角色查找文档

| 我是谁 / 想做什么 | 推荐阅读 |
|---|---|
| **初次了解项目**（定位、安装、最小示例） | [项目首页 README](../README.md) · [English README](../README_EN.md) |
| **组织一次决策评审或 Code Review** | [决策与 Code Review 使用指南](DECISION_WORKFLOW.md) |
| **在 Python / Hermes / MCP / HTTP 中接入** | [接入与 API 参考](INTEGRATION_AND_API.md) |
| **理解系统架构、27 个工具与 Schema v7** | [系统架构](architecture.md) |
| **排查消息确认、订阅、锁或 PDF 导出问题** | [技术可靠性与验证](TECHNICAL_RELIABILITY.md) |
| **了解产品方向、边界与真实验收案例** | [产品方向与近期计划](product/DIRECTION.md) · [Code Review 验收](product/CODE_REVIEW_ACCEPTANCE.md) · [WorkBuddy 付费 Skill 可行性评估](product/workbuddy-paid-skill-feasibility.md) |
| **贡献代码、运行测试或同步 SKILL.md** | [贡献指南](../CONTRIBUTING.md) · [SKILL.md 同步说明](SKILL_SYNC.md) |
| **查看品牌 Logo 与静态视觉资产清单** | [Logo 设计规范](design/DESIGN-SPEC.md)（静态资产位于 `docs/design/assets/`） |

## 给 AI Agent 看的规范文档

| 文件 | 适用对象 | 说明 |
|---|---|---|
| [SKILL.md](../SKILL.md) | ClawHub / 仓库根安装入口 | 由 `src/skills/SKILL.md` 单向自动同步生成，请勿直接编辑 |
| [src/skills/SKILL.md](../src/skills/SKILL.md) | Hermes / OpenClaw 运行态 Agent（唯一真源） | 定义角色边界、工具映射、材料包与证据/报告契约、主持人与参与者执行协议 |
| [src/roundtable/skills/mcp-roundtable/SKILL.md](../src/roundtable/skills/mcp-roundtable/SKILL.md) | 随 Python 包分发的 MCP 客户端 Agent | 覆盖 MCP 安装配置、共享数据库、可靠收件箱与评审执行规范 |
| [src/roundtable/mcp/prompts.py](../src/roundtable/mcp/prompts.py) | 通过 MCP Prompts / `roundtable_get_prompt` 获取提示词的宿主 | 运行时动态注入当前 `context_revision`、证据、材料目录与阶段发言 |

## 历史归档

早期的 Sprint 1–3 PRD、界面原型草案、初版技术方案与立项讨论记录已归档至 [docs/archive/](archive/README.md)，仅供历史溯源，不再作为当前能力或实现依据。
