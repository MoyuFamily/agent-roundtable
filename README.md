<p align="center">
  <img src="https://raw.githubusercontent.com/ParsifalC/roundtable/main/docs/design/assets/svg/roundtable-logo.svg" alt="Roundtable" width="128" height="128">
</p>

<h1 align="center">Roundtable</h1>

<p align="center">
  <strong>多智能体圆桌讨论引擎：让 AI Agent 围绕一个问题多轮发言、追踪共识分歧，并自动生成结构化结论。</strong>
</p>

<p align="center">
  <a href="#development"><img src="https://img.shields.io/badge/tests-passing-brightgreen.svg" alt="Tests"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache--2.0-blue.svg" alt="License: Apache-2.0"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="Python 3.10+"></a>
  <a href="#-核心特性"><img src="https://img.shields.io/badge/core-zero_dependencies-brightgreen.svg" alt="Zero Dependencies"></a>
</p>

<p align="center">
  <strong><a href="README.md">中文</a> · <a href="README_EN.md">English</a></strong>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/ParsifalC/roundtable/main/docs/design/assets/demo.gif" alt="Roundtable Demo" width="600">
</p>

---

## ⚡ 30 秒理解 Roundtable

当你让多个 AI Agent 讨论复杂问题时，真正麻烦的不是“让它们说话”，而是：

| 你关心的 | Roundtable 的答案 |
|---|---|
| 多 Agent 怎么协作？ | 用圆桌会议模型管理参与者、轮次和发言顺序 |
| 讨论有没有收敛？ | 自动追踪 convergence score、共识点和分歧点 |
| 结论怎么沉淀？ | 自动生成结构化 summary，可用于 PRD、架构评审、决策记录 |
| 能接入现有 Agent 系统吗？ | 框架无关，通过 adapter 接入 Hermes Agent 或任意 Agent 框架 |
| 运行成本高吗？ | 核心库零外部依赖，只使用 Python 标准库和 SQLite |

**一句话：你只管选人、定话题，Roundtable 帮你管理讨论过程、追踪分歧共识，并沉淀结论。**

## 🧩 适合场景

- **技术方案评审**：让架构师、后端、运维、安全角色分别发言，沉淀决策依据
- **产品决策讨论**：让产品、设计、开发、增长角色讨论 MVP 边界和优先级
- **代码 Review 辩论**：让不同 Agent 从质量、安全、性能角度审查实现方案
- **需求澄清**：让多个专家角色围绕模糊需求追问、反驳和收敛
- **多 Agent 工作流**：作为 coordinator 的讨论协议层，记录过程和结论

## 🚀 快速开始

### 安装

当前仓库尚未发布到 PyPI。请先从源码安装：

```bash
git clone https://github.com/ParsifalC/roundtable.git
cd roundtable
pip install -e .
```

> 说明：PyPI 上的 `roundtable` / `roundtable-ai` 目前不是本项目，请勿直接使用 `pip install roundtable` 安装。

### 基本用法

例如：让后端架构师、运维工程师、产品经理三个 Agent 讨论数据库选型，Roundtable 负责管理轮次、记录观点、追踪收敛并生成结论。

```python
from roundtable import RoundtableCore

core = RoundtableCore()

# 1. 创建讨论
result = core.create_discussion(
    topic="选择数据库：PostgreSQL vs MySQL vs TiDB",
    participants=[
        {"profile": "backend_architect", "role": "后端架构师", "display_name": "Backend Architect"},
        {"profile": "ops_engineer", "role": "运维工程师", "display_name": "Ops Engineer"},
        {"profile": "product_manager", "role": "产品经理", "display_name": "Product Manager"},
    ],
    max_rounds=3,
)
disc_id = result["discussion_id"]

# 2. 参与者发言
core.speak(disc_id, "backend_architect", "PostgreSQL 的 JSON 和事务能力更适合复杂业务建模。")
core.speak(disc_id, "ops_engineer", "MySQL 运维经验和工具链更成熟，团队上手成本低。")
core.speak(disc_id, "product_manager", "从迭代速度看，我们需要优先保证未来功能扩展能力。")

# 3. 查看讨论状态（含收敛度）
status = core.status(disc_id)
print(f"Convergence: {status['convergence_score']}")

# 4. 生成结构化总结
summary = core.summarize(disc_id, compact=True)
print(summary["structured_summary"])

# 5. 结束讨论
core.end_discussion(disc_id, conclusion="选择 PostgreSQL，优先支持复杂数据结构和长期扩展。")
```

### 错误安全模式（推荐用于生产环境）

```python
from roundtable.adapters.generic import Roundtable

rt = Roundtable(db_path="/tmp/discussions.db")
result = rt.init(topic="...", participants=[...])
# 所有方法返回 dict — 错误以 {"error": "msg"} 返回，永不抛异常
```

### 实时通知

```python
def my_send(platform, chat_id, message):
    print(f"[{platform}:{chat_id}] {message}")

rt = Roundtable(send_fn=my_send)
result = rt.init(
    topic="架构评审",
    participants=[...],
    notifications={
        "enabled": True,
        "channels": [
            {"platform": "feishu", "chat_id": "oc_xxx"},
            {"platform": "slack", "chat_id": "#engineering"},
        ],
        "events": ["round_end", "concluded"],
    },
)
```

## ✨ 核心特性

| 特性 | 说明 |
|------|------|
| 🧑‍⚖️ **圆桌讨论模型** | 用 topic、participants、rounds 管理多 Agent 讨论流程 |
| 📊 **收敛追踪** | 自动计算每轮共识度（convergence score），量化讨论进展 |
| 🧾 **结构化总结** | 输出共识、分歧、决策建议和结论，适合沉淀文档 |
| 🔌 **框架无关** | 独立运行，或通过 adapter 接入任何 Agent 框架 |
| 🔔 **实时通知** | 讨论事件推送到飞书、Slack 或任意消息平台 |
| 🛡️ **错误安全** | Generic adapter 所有方法返回 dict，永不抛异常 |
| 🗂️ **SQLite 持久化** | 讨论记录持久存储，随时回溯 |
| 🪶 **零依赖核心** | 核心库只用 Python 标准库（sqlite3 + dataclasses） |

## 🔌 为 Hermes Agent 集成而生

Roundtable 可以独立作为 Python 库使用，也可以作为 Hermes Agent 的 toolset 使用，让多个 Agent 通过工具调用参与同一场结构化讨论。

```yaml
# Hermes 配置
toolsets:
  - roundtable
```

安装 Hermes Agent 后，Roundtable 可注册讨论相关工具，AI Agent 能够创建、参与、读取、总结和结束讨论。

## 📐 架构

```text
src/roundtable/
├── __init__.py       # 公共 API
├── core.py           # 业务逻辑层
├── db.py             # SQLite 存储层
├── models.py         # 数据模型（dataclass）
├── notify.py         # 通知分发
├── exceptions.py     # 异常定义
└── adapters/
    ├── hermes.py     # Hermes Agent 适配器
    └── generic.py    # 通用 Python API（错误安全）
```

## 🛣️ 后续计划

- 明确并发布正式 PyPI 包名
- 补充 CLI 示例和端到端 Demo
- 增强结构化总结模板
- 补充更多 Agent 框架 adapter
- 增加讨论结果导出能力

## 🤝 贡献

1. Fork 本仓库
2. 创建特性分支：`git checkout -b feature/amazing-feature`
3. 编写测试并确保通过：`pytest tests/ -v`
4. 提交代码：`git commit -m 'feat: add amazing feature'`
5. 推送并创建 PR

### 代码规范

- Python 3.10+，使用 type hints
- 核心库零外部依赖（stdlib only）
- 所有异常继承 `RoundtableError`
- 所有公共方法返回 JSON-serializable dict

## 👥 团队

| 成员 | 角色 | 说明 |
|------|------|------|
| <img src="https://avatars.githubusercontent.com/u/286716759?v=4" width="24" height="24" style="border-radius:50%"> 饼哥 | 产品总监 | 十年产品老兵，擅长把模糊需求变成可落地的 MVP，信奉「用户要的不是钻头，是墙上的洞」 |
| <img src="https://avatars.githubusercontent.com/u/286719582?v=4" width="24" height="24" style="border-radius:50%"> 像素姐 | 设计总监 | UI/UX 与品牌视觉体系设计，专注交互细节与用户体验优化，信奉「细节决定品质感」 |
| <img src="https://avatars.githubusercontent.com/u/286715358?v=4" width="24" height="24" style="border-radius:50%"> 码飞 | 技术总监 | 全栈开发与系统架构设计，主导技术选型、性能优化和 AI/ML 工程化落地 |
| <img src="https://avatars.githubusercontent.com/u/286714101?v=4" width="24" height="24" style="border-radius:50%"> 小赫 | 协调者 | 团队任务统筹与进度管理，确保产品→设计→开发流程高效运转 |

## 📄 许可证

[Apache-2.0](LICENSE)
