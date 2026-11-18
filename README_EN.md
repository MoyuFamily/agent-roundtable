<p align="center">
  <img src="https://raw.githubusercontent.com/MoyuFamily/agent-roundtable/main/docs/design/assets/svg/roundtable-logo.svg" alt="Roundtable" width="128" height="128">
</p>

<h1 align="center">Roundtable</h1>

<p align="center">
  <strong>Turn scattered materials into evidence-backed, trade-off-aware, updatable decision and Code Review recommendations.</strong>
</p>

<p align="center">
  <a href="docs/TECHNICAL_RELIABILITY.md"><img src="https://img.shields.io/badge/tests-passing-brightgreen.svg" alt="Tests"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache--2.0-blue.svg" alt="License: Apache-2.0"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="Python 3.10+"></a>
  <a href="#quick-start"><img src="https://img.shields.io/badge/core-zero_dependencies-brightgreen.svg" alt="Zero Dependencies"></a>
</p>

<p align="center">
  <strong><a href="README.md">中文</a> · <a href="README_EN.md">English</a></strong>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/MoyuFamily/agent-roundtable/main/docs/design/assets/demo.gif" alt="Roundtable Demo" width="600">
</p>

---

## What is Roundtable

Roundtable is a lightweight protocol and storage layer for structured decision reviews and Code Reviews (PyPI package: `agent-roundtable`; Python import: `roundtable`). It focuses on **input handling** (extracting decision-relevant facts, preserving provenance and unknowns, and reading source segments on demand) and **output quality** (clear, actionable recommendations that stay consistent when facts change).

| Layer | Responsibility Boundary |
|-------|-------------------------|
| **Roles & User** | Roles define domain responsibilities; the user owns objectives, preferences, and the final decision |
| **Host & Agents** | The host executes agents, selects models, extracts/verifies materials, and synthesizes findings; Roundtable does not run models or auto-pick teams |
| **Roundtable Engine** | Zero-dependency Python stdlib + SQLite store for rounds/speeches, versioned briefs/evidence/materials, citation checks, unified Markdown/PDF reports, and a live Web Viewer |

> Multiple roles, agents, and models are tools for catching blind spots—not a default requirement. Simple lookups or easily reversible choices can use a single assistant. See [Product Direction](docs/product/DIRECTION.md) (Chinese) for details and evaluation criteria.

## Quick Start

### 1. Installation

```bash
pip install agent-roundtable
```

To test the current source branch locally:

```bash
git clone https://github.com/MoyuFamily/agent-roundtable.git
cd agent-roundtable
pip install -e .
```

| Optional Extra | Install Command | Purpose |
|----------------|-----------------|---------|
| `mcp` | `pip install "agent-roundtable[mcp]"` | MCP server (stdio / HTTP-SSE) and platform config installer |
| `materials` | `pip install "agent-roundtable[materials]"` | Local page-by-page PDF text extraction (`pypdf`, no OCR) |
| `web` | `pip install "agent-roundtable[web]"` | Use `nanoid` for Web Viewer share tokens (falls back to stdlib `secrets`) |
| `dev` | `pip install -e ".[dev,mcp,materials]"` | Local tests (`pytest`), lint (`ruff`), and type checking (`mypy`) |

> Note: The official PyPI package is **`agent-roundtable`**. Unrelated `roundtable` / `roundtable-ai` packages on PyPI are not this project.

### 2. Multi-Agent MCP & HTTP Setup

- **MCP clients (Claude Code / Cursor / Windsurf)**:
  ```bash
  pip install -e ".[mcp]" "mcp>=1,<2"
  python3 -m roundtable.skills.mcp-roundtable.install --platform=auto
  ```
- **HTTP Bridge (Codex / WorkBuddy / HTTP-capable hosts)**:
  ```bash
  python3 -m roundtable.codex  # listens on http://127.0.0.1:8201 by default
  ```
- **Hermes Agent**: enable `toolsets: [roundtable]` in your profile configuration.

Runtime AI agent specifications are maintained in English at [SKILL.md](SKILL.md) and [MCP Skill](src/roundtable/skills/mcp-roundtable/SKILL.md).

### 3. Minimal Python Example

This snippet demonstrates recording a review with `RoundtableCore` (in real usage, the host runs each role agent and submits their speeches):

```python
from roundtable import RoundtableCore

core = RoundtableCore()

# 1. Create a discussion (web=True starts the local Web Viewer best-effort)
result = core.create_discussion(
    topic="Choose database: PostgreSQL vs MySQL vs TiDB",
    participants=[
        {"profile": "backend_architect", "role": "Backend Architect"},
        {"profile": "ops_engineer", "role": "Ops Engineer"},
        {"profile": "product_manager", "role": "Product Manager"},
    ],
    max_rounds=3,
)
disc_id = result["discussion_id"]

# 2. Coordinator opening (round 0) and participant turns
core.speak(disc_id, "coordinator", "Opening: compare options on modeling fit and ops cost.")
core.speak(disc_id, "backend_architect", "PostgreSQL JSON and transactions fit complex models.")
core.speak(disc_id, "ops_engineer", "Team knows MySQL tooling best; migration cost needs checks.")
core.speak(disc_id, "product_manager", "Prioritize iteration headroom over the next 6 months.")

# 3. Inspect formatted summary and record a recommendation (distinct from user approval)
summary = core.summarize(disc_id, compact=True)
core.end_discussion(
    disc_id,
    conclusion="Recommend PostgreSQL pending migration/ops validation. Awaiting user decision.",
)
```

- **Web Viewer**: Requires Node.js 18+. `create_discussion()` returns `web_status` (`ready` / `failed` / `disabled`), `web_url`, `web_error`, and `web_help` without blocking core creation. Markdown export always works; set `PUPPETEER_EXECUTABLE_PATH` to an existing Chrome/Chromium binary for PDF export.
- **Error-Safe Mode**: Production hosts can use `from roundtable.adapters.generic import Roundtable`, where every method returns a JSON-serializable `dict` (`{"error": "..."}` on failure) and never raises.

## Supported Scenarios

All seven scenarios share the same brief, evidence, independent first-pass, and reconciliation workflow with tailored roles and deliverables (see the [scenario catalog](docs/product/DIRECTION.md#场景清单), Chinese):

- **Project direction**: continue, pivot, defer, or stop with clear investment boundaries
- **Product scope & priorities**: target users, MVP scope, trade-offs, and deferred items
- **Technical choices**: build vs. buy, architecture, migrations, and maintenance costs
- **Release & implementation**: launch gates, blockers, rollout steps, and rollback criteria
- **Resources & business models**: budget/headcount allocation; free, subscription, or usage pricing
- **Workflows & tool selection**: compare trial evidence against baseline effort, migration, and exit costs
- **Code Review**: inspect concrete diffs for correctness, architecture, security, and reliability with grounded locations and merge recommendations

## Documentation

| Document | Scope |
|----------|-------|
| [SKILL.md](SKILL.md) | **Runtime AI specification (EN)**: Hermes/MCP/HTTP contracts, shared evidence, material packets, coordinator & participant checklists |
| [MCP Skill](src/roundtable/skills/mcp-roundtable/SKILL.md) | **MCP runtime skill (EN)**: bundled inside the Python package for MCP hosts |
| [docs/README.md](docs/README.md) | Documentation index (Chinese) |
| [docs/DECISION_WORKFLOW.md](docs/DECISION_WORKFLOW.md) | Decision & Code Review workflow, material import, templates, structured evidence & reports (Chinese) |
| [docs/INTEGRATION_AND_API.md](docs/INTEGRATION_AND_API.md) | Integration modes, Python Core/Facade API, MCP/HTTP bridges, custom `RoundtableAdapter` & env vars (Chinese) |
| [docs/architecture.md](docs/architecture.md) | System overview, state machine, 27 MCP tools, DB schema v7 & deployment modes (Chinese) |
| [docs/TECHNICAL_RELIABILITY.md](docs/TECHNICAL_RELIABILITY.md) | Inbox ack protocol, MCP cross-process subscriptions, file locks & isolated PDF export (Chinese) |
| [docs/product/DIRECTION.md](docs/product/DIRECTION.md) | Product strategy, boundaries & [Code Review acceptance report](docs/product/CODE_REVIEW_ACCEPTANCE.md) (Chinese) |

> Note: Docs reflect the current source tree; verify package version before assuming published PyPI builds include unreleased source changes.

## Contributing, Team & License

See [CONTRIBUTING.md](CONTRIBUTING.md) for local setup, test/lint commands, and PR expectations.

| Member | Role | Focus |
|--------|------|-------|
| <img src="https://avatars.githubusercontent.com/u/286716759?v=4" width="24" height="24" style="border-radius:50%"> Bingge | Product Director | Turning ambiguous goals into concrete MVP scope and decision criteria |
| <img src="https://avatars.githubusercontent.com/u/286719582?v=4" width="24" height="24" style="border-radius:50%"> Pixel | Design Director | Information architecture, brand visuals, and interaction quality |
| <img src="https://avatars.githubusercontent.com/u/286715358?v=4" width="24" height="24" style="border-radius:50%"> Mafei | Tech Director | System architecture, reliability engineering, and cross-platform bridges |
| <img src="https://avatars.githubusercontent.com/u/286714101?v=4" width="24" height="24" style="border-radius:50%"> Xiaohe | Coordinator | Cross-role workflow orchestration and review synthesis |

[Apache-2.0](LICENSE)
