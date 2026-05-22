<p align="center">
  <img src="https://raw.githubusercontent.com/ParsifalC/roundtable/main/docs/design/assets/svg/roundtable-logo.svg" alt="Roundtable" width="128" height="128">
</p>

<h1 align="center">Roundtable</h1>

<p align="center">
  <strong>让多个 AI 坐下来开会讨论，自动追踪共识与分歧，得出结论。</strong>
</p>

<p align="center">
  <a href="https://pypi.org/project/roundtable-ai/"><img src="https://img.shields.io/pypi/v/roundtable-ai.svg" alt="PyPI version"></a>
  <a href="#development"><img src="https://img.shields.io/badge/tests-passing-brightgreen.svg" alt="Tests"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="Python 3.10+"></a>
  <a href="#installation"><img src="https://img.shields.io/badge/dependencies-zero-brightgreen.svg" alt="Zero Dependencies"></a>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/ParsifalC/roundtable/main/docs/design/assets/demo.gif" alt="Roundtable Demo" width="600">
</p>

---

## ⚡ 3 行代码，开个会

```python
from roundtable import RoundtableCore

core = RoundtableCore()
result = core.create_discussion(
    topic="Should we use PostgreSQL or MySQL?",
    participants=[
        {"profile": "alice", "role": "Backend Engineer"},
        {"profile": "bob", "role": "DBA"},
    ],
    max_rounds=3,
)
# 开始讨论
core.speak(result["discussion_id"], "alice", "PostgreSQL has better JSON support.")
core.speak(result["discussion_id"], "bob", "MySQL is simpler to operate at scale.")
```

## 🎯 为什么需要 Roundtable？

当你让多个 AI Agent 讨论一个复杂问题时，通常需要自己管理：
- **谁先说？谁后说？** → Roundtable 自动管理发言顺序
- **说了什么？达成共识了吗？** → 自动追踪 convergence score
- **讨论怎么结束？结论在哪？** → 自动生成结构化总结
- **实时知道进展？** → 推送通知到飞书/Slack/任意平台

**一句话：你只管选人、定话题，Roundtable 帮你管剩下的一切。**

## ✨ 核心特性

| 特性 | 说明 |
|------|------|
| 🪶 **零依赖** | 只用 Python 标准库（sqlite3 + dataclasses），不会给你添包 |
| 🔌 **框架无关** | 独立运行，或通过 adapter 接入任何 Agent 框架 |
| 📊 **收敛追踪** | 自动计算每轮共识度（convergence score），量化讨论进展 |
| 🔔 **实时通知** | 讨论事件推送到飞书、Slack 或任意消息平台 |
| 🛡️ **错误安全** | Generic adapter 所有方法返回 dict，永不抛异常 |
| 🗂️ **SQLite 持久化** | 讨论记录持久存储，随时回溯 |

## 📦 安装

```bash
pip install roundtable
```

从源码安装：

```bash
git clone https://github.com/ParsifalC/roundtable.git
cd roundtable
pip install -e .
```

## 🚀 快速开始

### 基本用法

```python
from roundtable import RoundtableCore

core = RoundtableCore()

# 1. 创建讨论
result = core.create_discussion(
    topic="选择前端框架：React vs Vue vs Svelte",
    participants=[
        {"profile": "alice", "role": "全栈工程师", "display_name": "Alice"},
        {"profile": "bob", "role": "前端 Lead", "display_name": "Bob"},
        {"profile": "carol", "role": "产品经理", "display_name": "Carol"},
    ],
    max_rounds=3,
)
disc_id = result["discussion_id"]

# 2. 参与者发言
core.speak(disc_id, "alice", "Svelte 编译时优化性能最好...")
core.speak(disc_id, "bob", "React 生态最成熟，招人容易...")
core.speak(disc_id, "carol", "从产品迭代速度看，Vue 的学习曲线最低...")

# 3. 查看讨论状态（含收敛度）
status = core.status(disc_id)
print(f"Convergence: {status['convergence_score']}")

# 4. 生成总结
summary = core.summarize(disc_id, compact=True)
print(summary["structured_summary"])

# 5. 结束讨论
core.end_discussion(disc_id, conclusion="选择 Vue 3 + Vite")
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

## 🔌 与 Hermes Agent 集成

安装 Hermes Agent 后，Roundtable 自动注册 9 个工具：

```yaml
# Hermes 配置
toolsets:
  - roundtable
```

无需额外代码，AI Agent 即可通过工具调用来创建、参与、管理讨论。

## 📐 架构

```
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

## 🤝 贡献

1. Fork 本仓库
2. 创建特性分支：`git checkout -b feature/amazing-feature`
3. 编写测试并确保通过：`pytest tests/ -v`
4. 提交代码：`git commit -m 'feat: add amazing feature'`
5. 推送并创建 PR

### 代码规范

- Python 3.10+，使用 type hints
- **零外部依赖**（stdlib only）
- 所有异常继承 `RoundtableError`
- 所有公共方法返回 JSON-serializable dict

## 👥 团队

| 成员 | 角色 | 说明 |
|------|------|------|
| 🎯 饼哥 | 产品总监 | 十年产品老兵，擅长把模糊需求变成可落地的 MVP，信奉「用户要的不是钻头，是墙上的洞」 |
| 🎨 像素姐 | 设计师 | *待补充* |
| 💻 码飞 | 技术总监 | 全栈开发与系统架构设计，主导技术选型、性能优化和 AI/ML 工程化落地 |
| 🤖 小赫 | 协调者 | 团队任务统筹与进度管理，确保产品→设计→开发流程高效运转 |

## 📄 许可证

[MIT](LICENSE)
