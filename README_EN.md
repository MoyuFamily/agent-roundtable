<p align="center">
  <img src="https://raw.githubusercontent.com/ParsifalC/roundtable/main/docs/design/assets/svg/roundtable-logo.svg" alt="Roundtable" width="128" height="128">
</p>

<h1 align="center">Roundtable</h1>

<p align="center">
  <strong>Let multiple AIs sit down and discuss, automatically track consensus and disagreements, and reach conclusions.</strong>
</p>

<p align="center">
  <a href="https://pypi.org/project/roundtable-ai/"><img src="https://img.shields.io/pypi/v/roundtable-ai.svg" alt="PyPI version"></a>
  <a href="#development"><img src="https://img.shields.io/badge/tests-passing-brightgreen.svg" alt="Tests"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="Python 3.10+"></a>
  <a href="#installation"><img src="https://img.shields.io/badge/dependencies-zero-brightgreen.svg" alt="Zero Dependencies"></a>
</p>

<p align="center">
  <strong><a href="README.md">中文</a> · <a href="README_EN.md">English</a></strong>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/ParsifalC/roundtable/main/docs/design/assets/demo.gif" alt="Roundtable Demo" width="600">
</p>

---

## ⚡ 3 Lines of Code to Start a Discussion

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
# Start discussion
core.speak(result["discussion_id"], "alice", "PostgreSQL has better JSON support.")
core.speak(result["discussion_id"], "bob", "MySQL is simpler to operate at scale.")
```

## 🎯 Why Roundtable?

When you let multiple AI Agents discuss a complex problem, you usually need to manage:
- **Who speaks first? Who speaks next?** → Roundtable automatically manages speaking order
- **What was said? Did they reach consensus?** → Automatically tracks convergence score
- **How does the discussion end? Where's the conclusion?** → Auto-generates structured summary
- **Real-time progress?** → Push notifications to Feishu/Slack/any platform

**In one sentence: You just pick the people and set the topic, Roundtable handles the rest.**

## ✨ Core Features

| Feature | Description |
|---------|-------------|
| 🪶 **Zero Dependencies** | Only uses Python stdlib (sqlite3 + dataclasses), won't add bloat |
| 🔌 **Framework Agnostic** | Run standalone, or integrate with any Agent framework via adapters |
| 📊 **Convergence Tracking** | Auto-calculates consensus score per round, quantifying discussion progress |
| 🔔 **Real-time Notifications** | Push discussion events to Feishu, Slack, or any messaging platform |
| 🛡️ **Error-Safe** | Generic adapter returns dict for all methods, never throws exceptions |
| 🗂️ **SQLite Persistence** | Discussion records stored persistently, always traceable |

## 📦 Installation

```bash
pip install roundtable
```

From source:

```bash
git clone https://github.com/ParsifalC/roundtable.git
cd roundtable
pip install -e .
```

## 🚀 Quick Start

### Basic Usage

```python
from roundtable import RoundtableCore

core = RoundtableCore()

# 1. Create a discussion
result = core.create_discussion(
    topic="Choose frontend framework: React vs Vue vs Svelte",
    participants=[
        {"profile": "alice", "role": "Full-stack Engineer", "display_name": "Alice"},
        {"profile": "bob", "role": "Frontend Lead", "display_name": "Bob"},
        {"profile": "carol", "role": "Product Manager", "display_name": "Carol"},
    ],
    max_rounds=3,
)
disc_id = result["discussion_id"]

# 2. Participants speak
core.speak(disc_id, "alice", "Svelte has the best performance with compile-time optimization...")
core.speak(disc_id, "bob", "React has the most mature ecosystem, easier to hire...")
core.speak(disc_id, "carol", "From product iteration speed, Vue has the lowest learning curve...")

# 3. Check discussion status (with convergence score)
status = core.status(disc_id)
print(f"Convergence: {status['convergence_score']}")

# 4. Generate summary
summary = core.summarize(disc_id, compact=True)
print(summary["structured_summary"])

# 5. End discussion
core.end_discussion(disc_id, conclusion="Choose Vue 3 + Vite")
```

### Error-Safe Mode (Recommended for Production)

```python
from roundtable.adapters.generic import Roundtable

rt = Roundtable(db_path="/tmp/discussions.db")
result = rt.init(topic="...", participants=[...])
# All methods return dict — errors returned as {"error": "msg"}, never throws
```

### Real-time Notifications

```python
def my_send(platform, chat_id, message):
    print(f"[{platform}:{chat_id}] {message}")

rt = Roundtable(send_fn=my_send)
result = rt.init(
    topic="Architecture Review",
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

## 🔌 Hermes Agent Integration

After installing Hermes Agent, Roundtable auto-registers 9 tools:

```yaml
# Hermes config
toolsets:
  - roundtable
```

No extra code needed — AI Agents can create, participate in, and manage discussions via tool calls.

## 📐 Architecture

```
src/roundtable/
├── __init__.py       # Public API
├── core.py           # Business logic layer
├── db.py             # SQLite storage layer
├── models.py         # Data models (dataclass)
├── notify.py         # Notification dispatch
├── exceptions.py     # Exception definitions
└── adapters/
    ├── hermes.py     # Hermes Agent adapter
    └── generic.py    # Generic Python API (error-safe)
```

## 🤝 Contributing

1. Fork this repository
2. Create feature branch: `git checkout -b feature/amazing-feature`
3. Write tests and ensure they pass: `pytest tests/ -v`
4. Commit code: `git commit -m 'feat: add amazing feature'`
5. Push and create PR

### Code Standards

- Python 3.10+, use type hints
- **Zero external dependencies** (stdlib only)
- All exceptions inherit `RoundtableError`
- All public methods return JSON-serializable dict

## 👥 Team

| Member | Role | Description |
|--------|------|-------------|
| <img src="https://avatars.githubusercontent.com/u/286716759?v=4" width="24" height="24" style="border-radius:50%"> Bingge | Product Director | 10+ years product veteran, expert at turning vague requirements into actionable MVPs, believes "users don't want a drill, they want a hole in the wall" |
| <img src="https://avatars.githubusercontent.com/u/286719582?v=4" width="24" height="24" style="border-radius:50%"> Pixel | Design Director | UI/UX and brand visual system design, focuses on interaction details and UX optimization, believes "details determine quality" |
| <img src="https://avatars.githubusercontent.com/u/286715358?v=4" width="24" height="24" style="border-radius:50%"> Mafei | Tech Director | Full-stack development and system architecture design, leads tech selection, performance optimization, and AI/ML engineering |
| <img src="https://avatars.githubusercontent.com/u/286714101?v=4" width="24" height="24" style="border-radius:50%"> Xiaohe | Coordinator | Team task coordination and progress management, ensures product→design→development workflow runs efficiently |

## 📄 License

[MIT](LICENSE)
