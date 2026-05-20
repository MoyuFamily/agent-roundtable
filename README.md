# Roundtable

Framework-agnostic multi-agent roundtable discussion library for Python.

## Features

- **Zero dependencies** — only Python stdlib (sqlite3, dataclasses, json)
- **Framework-agnostic** — works standalone or with any agent framework
- **Structured discussions** — multi-round, tracked convergence, findings
- **7 operations** — init, speak, read, status, summarize, end, list
- **Adapters** — built-in support for Hermes Agent, generic Python API

## Quick Start

```python
from roundtable import RoundtableCore

core = RoundtableCore()

# Create a discussion
result = core.create_discussion(
    topic="Should we use PostgreSQL or MySQL?",
    participants=[
        {"profile": "alice", "role": "Backend Engineer", "display_name": "Alice"},
        {"profile": "bob", "role": "DBA", "display_name": "Bob"},
    ],
    max_rounds=3,
)
disc_id = result["discussion_id"]

# Participants speak
core.speak(disc_id, "alice", "PostgreSQL has better JSON support.")
core.speak(disc_id, "bob", "MySQL is simpler to operate at scale.")

# Read history
history = core.read(disc_id)
print(history["formatted_history"])

# End discussion
core.end_discussion(disc_id, conclusion="We chose PostgreSQL")
```

## Generic API (error-safe)

```python
from roundtable.adapters.generic import Roundtable

rt = Roundtable(db_path="/tmp/my_discussions.db")
result = rt.init(topic="...", participants=[...])
# All methods return dicts — errors as {"error": "msg"}, never raise
```

## Installation

```bash
pip install roundtable
```

Or from source:

```bash
git clone https://github.com/ParsifalC/roundtable.git
cd roundtable
pip install -e .
```

## Hermes Agent Integration

When installed alongside Hermes Agent, the adapter auto-registers all 7 tools:

```yaml
# In your Hermes profile config
toolsets:
  - roundtable
```

The adapter lives in `roundtable.adapters.hermes` and registers tools
via Hermes' tool discovery system.

## Architecture

```
src/roundtable/
├── __init__.py       # Public API exports
├── models.py         # Dataclasses (Discussion, Speech, Participant, etc.)
├── exceptions.py     # Custom exceptions (all inherit ValueError)
├── db.py             # RoundtableDB — SQLite storage layer
├── core.py           # RoundtableCore — business logic layer
└── adapters/
    ├── hermes.py     # Hermes Agent tool adapter
    └── generic.py    # Generic Python API (error-safe facade)
```

## Development

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

## License

MIT
