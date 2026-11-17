<p align="center">
  <img src="https://raw.githubusercontent.com/MoyuFamily/agent-roundtable/main/docs/design/assets/svg/roundtable-logo.svg" alt="Roundtable" width="128" height="128">
</p>

<h1 align="center">Roundtable</h1>

<p align="center">
  <strong>Roundtable aims to turn scattered material into decision recommendations with supporting evidence, clear trade-offs, and a basis for revision as information changes.</strong>
</p>

<p align="center">
  <a href="#development"><img src="https://img.shields.io/badge/tests-passing-brightgreen.svg" alt="Tests"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache--2.0-blue.svg" alt="License: Apache-2.0"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="Python 3.10+"></a>
  <a href="#-core-features"><img src="https://img.shields.io/badge/core-zero_dependencies-brightgreen.svg" alt="Zero Dependencies"></a>
</p>

<p align="center">
  <strong><a href="README.md">中文</a> · <a href="README_EN.md">English</a></strong>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/MoyuFamily/agent-roundtable/main/docs/design/assets/demo.gif" alt="Roundtable Demo" width="600">
</p>

---

## Product Direction

Roundtable will build its strengths by continually improving **how it handles input** and **the quality of its output**. The review goals are:

| Area of improvement | Review requirements |
|---|---|
| Input handling | Extract information relevant to the decision; identify sources, versions, and applicability; distinguish facts, estimates, and unknowns; identify gaps and conflicts |
| Output quality | Keep recommendations clear, concise, and actionable: include conclusions, supporting evidence, costs, conditions that would change the assessment, and next steps; provide detailed evidence as needed |

**Roles define responsibilities; agents bring context and tools; models perform analysis.** These can be configured separately. There is no fixed mapping from a model to a job title, and reviews do not always need more roles or models.

Multiple roles, agents, and models are methods for supporting these goals. Their contribution to Roundtable requires comparative evaluation; an advantage over a single assistant has not been established.

## Current Capabilities

The Python core manages discussions, speaking order, references, SQLite records, formatted summaries, and a Web Viewer. Skills and MCP prompts guide the host through the review. The `decision-support` and `code-review` templates supply editable role responsibilities.

**The user or coordinator selects roles; the host runs agents and selects models; the user makes the decision.** Extracting relevant material, checking sources and applicability, distinguishing facts, estimates, and unknowns, and synthesizing conclusions currently depend on the user, coordinator, and host. Existing records and conclusions can be exported as Markdown or rendered as PDF with an available browser. Automatic material parsing, semantic verification, evidence-change impact analysis, analytical chart generation, and consistency checks on external artifacts are not implemented. The engine also does not provide automatic team selection, model routing, or semantic finding extraction.

`convergence_score` is calculated from externally supplied consensus/disagreement annotations and may be `None`; it is not answer accuracy. `summarize()` formats recorded material rather than performing professional synthesis.

The current source stores structured evidence with brief revisions, validates report references and the expected revision, and renders one saved conclusion for reads, the Viewer, and Markdown/PDF exports. The coordinator still checks facts and reasoning. Brief history with provenance, speech-linked annotations, and HTTP prompt retrieval are also available. See the [workflow guide](docs/DECISION_WORKFLOW.md) for interfaces and examples.

See the [product direction and acceptance criteria](docs/product/DIRECTION.md) and [decision workflow guide](docs/DECISION_WORKFLOW.md) (Chinese). These changes describe the source tree; check a published package's version and capabilities before assuming it includes them.

## 🧩 Use Cases

- **Project direction**: continue, change, defer, or stop; define investment boundaries.
- **Product scope and priorities**: choose users, MVP boundaries, and deferred needs.
- **Technical choices**: build or buy, architecture, migrations, and maintenance costs.
- **Release and implementation**: identify launch conditions, blockers, rollout steps, and rollback conditions.
- **Resources and business models**: allocate budget and people; compare free, subscription, and usage-based pricing.
- **Workflows and tool selection**: compare benefits with migration, training, maintenance, and exit costs.
- **Code Review**: inspect concrete changes from correctness, design, security, and reliability perspectives; deliver actionable findings and a merge recommendation.

All seven scenarios are in scope; validation can proceed in batches. They share a review workflow with scenario-specific roles, materials, and deliverables, rather than seven completed automation products. See the [scenario catalog](docs/product/DIRECTION.md#场景清单). Simple facts and easily reversible choices may only need one assistant.

## 🚀 Quick Start

### Installation

The official PyPI package name is `agent-roundtable`:

```bash
pip install agent-roundtable
```

Use source installation when you need to validate the current branch or local changes:

```bash
git clone https://github.com/MoyuFamily/agent-roundtable.git
cd agent-roundtable
pip install -e .
```

> Note: The existing `roundtable` / `roundtable-ai` packages on PyPI are not this project. Do not install this project with `pip install roundtable`.

### Codex Bridge

For a host that needs HTTP access, start the built-in bridge. From the source checkout above (the current server interface is validated against MCP 1.x):

```bash
pip install -e ".[mcp]" "mcp>=1,<2"
python -m roundtable.codex
```

The bridge registers a local Codex agent and exposes `/health`, `/agent`, `/inbox`, `/tool`, `/speak`, and `/status/<discussion_id>` on `http://127.0.0.1:8201`.

### Basic Usage

This example records supplied speeches and a recommendation. Roundtable manages rounds and storage; the host runs the actual role agents. This example does not call a model.

```python
from roundtable import RoundtableCore

core = RoundtableCore()

# 1. Create a discussion
result = core.create_discussion(
    topic="Choose database: PostgreSQL vs MySQL vs TiDB",
    participants=[
        {"profile": "backend_architect", "role": "Backend Architect", "display_name": "Backend Architect"},
        {"profile": "ops_engineer", "role": "Ops Engineer", "display_name": "Ops Engineer"},
        {"profile": "product_manager", "role": "Product Manager", "display_name": "Product Manager"},
    ],
    max_rounds=3,
)
disc_id = result["discussion_id"]
if result["web_status"] == "ready":
    print(f"Web Viewer: {result['web_url']}")
elif result["web_status"] == "failed":
    print(result["web_error"])
    print(result["web_help"])

# 2. Coordinator opening statement (round 0 is reserved for coordinator)
core.speak(disc_id, "coordinator", "Opening: let's discuss the database choice.")

# 3. Participants speak
core.speak(disc_id, "backend_architect", "PostgreSQL has stronger JSON and transaction support for complex business modeling.")
core.speak(disc_id, "ops_engineer", "MySQL has more mature operational experience and tooling in our team.")
core.speak(disc_id, "product_manager", "From an iteration perspective, we need room for future feature expansion.")

# 4. Check status (convergence is None without externally supplied findings)
status = core.status(disc_id)
print(f"Convergence: {status['convergence_score']}")

# 5. Get a formatted summary for the coordinator to verify and synthesize
summary = core.summarize(disc_id, compact=True)
print(summary["structured_summary"])

# 6. Record a recommendation separately from a user-approved decision
core.end_discussion(disc_id, conclusion="Recommend PostgreSQL; validate migration cost and ops readiness. Pending user decision.")
```

### Default Web Viewer

`create_discussion()` defaults to `web=True` and starts the local Web Viewer on a best-effort path. Discussion creation takes priority; if Node.js is missing, npm dependency installation fails, or the port is unavailable, the result includes:

- `web_status`: `"ready"`, `"failed"`, or `"disabled"`
- `web_url`: viewer URL, or `None` on failure
- `web_error` / `web_help`: readable diagnostics and next steps

The Web Viewer needs Node.js 18+. Roundtable reuses an existing healthy server, tries `node server.mjs`, and may run local `npm install --omit=dev` for missing web dependencies. It does not install Node itself or silently install global PM2. Automatic install skips Puppeteer's Chromium download; Markdown export always works, while PDF export returns a clear diagnostic when a browser is unavailable.

Set `PUPPETEER_EXECUTABLE_PATH` to use an existing Chrome/Chromium installation. PDF requests use isolated rendering processes; raw HTML and remote images in discussion content are rendered as inert text. See the [reliability guide](docs/TECHNICAL_RELIABILITY.md).

### Error-Safe Mode (Recommended for Production)

```python
from roundtable.adapters.generic import Roundtable

rt = Roundtable(db_path="/tmp/discussions.db")
result = rt.init(topic="...", participants=[...])
# All methods return dict — errors are returned as {"error": "msg"}, never thrown
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

## ✨ Core Features

| Feature | Description |
|---------|-------------|
| 🧑‍⚖️ **Roundtable Discussion Model** | Manage multi-agent discussions with topic, participants, and rounds |
| 📊 **Annotation Ratio** | Calculate a ratio from supplied findings; no automatic extraction or quality assessment |
| 🧾 **Decision Materials** | Format records for the coordinator to compare options, retain dissent, and record a recommendation |
| 🔌 **Host Integration** | Record reviews via Python, tools, or bridges; hosts execute agents and select models |
| 🖥️ **Default Web Viewer** | Best-effort real-time viewer on discussion creation; viewer failures do not block core discussions |
| 🔔 **Real-time Notifications** | Push discussion events to Feishu, Slack, or any messaging platform |
| 🛡️ **Error-Safe** | Generic adapter returns dict for all methods and never throws exceptions |
| 🗂️ **SQLite Persistence** | Persist discussion records for later review and traceability |
| 🪶 **Zero-Dependency Core** | Core library uses only Python stdlib (`sqlite3` + `dataclasses`) |

## 🔌 Built for Hermes Agent Integration

Roundtable can be used as a standalone Python library or as a Hermes Agent toolset, letting multiple agents participate in the same structured discussion via tool calls.

```yaml
# Hermes config
toolsets:
  - roundtable
```

After installing Hermes Agent, Roundtable can register discussion tools so AI agents can create, participate in, read, summarize, and end discussions.

## 📐 Architecture

```text
src/roundtable/
├── __init__.py       # Public API
├── core.py           # Business logic layer
├── db.py             # SQLite storage layer
├── models.py         # Data models (dataclass)
├── notify.py         # Notification dispatch
├── exceptions.py     # Exception definitions
├── web_publisher.py  # Local Web Viewer publisher
├── adapters/         # Hermes / generic adapters
├── mcp/              # MCP server, tools, and cross-platform bridges
├── web/              # Web Viewer static assets and Node server
└── templates/        # Discussion templates
```

## 🛣️ Roadmap

1. **Improve the path from materials to advice**: check for missing material, source applicability, and confusion between facts and estimates; deliver concise, actionable recommendations consistent with the detailed evidence.
2. **Update conclusions reliably**: reconsider affected judgments when information changes, explain the differences, and update or mark superseded outputs.
3. **Validate the contribution of collaboration and automation**: compare with a single assistant and independent role summaries using comparable material and budgets; use quality improvements and coordination costs to decide whether to add roles, models, or automation.

MCP compatibility, notifications, message acknowledgement, two-client flows, and package checks remain a maintained reliability foundation. Expand input and delivery formats based on observed benefits, then decide whether to maintain a standalone product, keep a lightweight skill, or reduce scope. See [product direction](docs/product/DIRECTION.md).

## 🤝 Contributing

1. Fork this repository
2. Create feature branch: `git checkout -b feature/amazing-feature`
3. Write tests and ensure they pass: `pytest tests/ -v`
4. Commit code: `git commit -m 'feat: add amazing feature'`
5. Push and create PR

### Code Standards

- Python 3.10+, use type hints
- Zero external dependencies in the core library
- Custom business exceptions inherit `RoundtableError`; validation and environment errors may use standard exceptions
- High-level Core / adapter methods return JSON-serializable dict

## 👥 Team

| Member | Role | Description |
|--------|------|-------------|
| <img src="https://avatars.githubusercontent.com/u/286716759?v=4" width="24" height="24" style="border-radius:50%"> Bingge | Product Director | 10+ years product veteran, expert at turning vague requirements into actionable MVPs, believes "users don't want a drill, they want a hole in the wall" |
| <img src="https://avatars.githubusercontent.com/u/286719582?v=4" width="24" height="24" style="border-radius:50%"> Pixel | Design Director | UI/UX and brand visual system design, focuses on interaction details and UX optimization, believes "details determine quality" |
| <img src="https://avatars.githubusercontent.com/u/286715358?v=4" width="24" height="24" style="border-radius:50%"> Mafei | Tech Director | Full-stack development and system architecture design, leads tech selection, performance optimization, and AI/ML engineering |
| <img src="https://avatars.githubusercontent.com/u/286714101?v=4" width="24" height="24" style="border-radius:50%"> Xiaohe | Coordinator | Team task coordination and progress management, ensures product→design→development workflow runs efficiently |

## 📄 License

[Apache-2.0](LICENSE)
