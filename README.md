# Roundtable

[![PyPI version](https://img.shields.io/pypi/v/roundtable.svg)](https://pypi.org/project/roundtable/)
[![Tests](https://img.shields.io/badge/tests-passing-brightgreen.svg)](#development)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

Framework-agnostic multi-agent roundtable discussion library for Python.

## Features

- **Zero dependencies** — only Python stdlib (sqlite3, dataclasses, json)
- **Framework-agnostic** — works standalone or with any agent framework
- **Structured discussions** — multi-round, tracked convergence, findings
- **9 operations** — init, speak, read, status, summarize, end, list, advance, notify
- **Notification push** — real-time event notifications to messaging channels
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

The generic adapter wraps `RoundtableCore` and returns errors as dicts instead of raising exceptions — ideal for untrusted callers.

```python
from roundtable.adapters.generic import Roundtable

rt = Roundtable(db_path="/tmp/my_discussions.db")
result = rt.init(topic="...", participants=[...])
# All methods return dicts — errors as {"error": "msg"}, never raise
```

### With notifications

```python
def my_send(platform, chat_id, message):
    print(f"[{platform}:{chat_id}] {message}")

rt = Roundtable(send_fn=my_send)
result = rt.init(
    topic="Architecture review",
    participants=[...],
    notifications={
        "enabled": True,
        "channels": [{"platform": "console", "chat_id": "default"}],
        "events": ["speech", "round_end", "concluded"],
    },
)
```

### Advance & Notify

```python
# Explicitly advance to next round
rt.advance(discussion_id)

# Manually trigger a notification
rt.notify(discussion_id, "round_start", round_num=1)
```

## Notification System

Roundtable supports real-time push notifications to messaging channels.

### Events

| Event | When |
|-------|------|
| `round_start` | First speech in a new round |
| `speech` | Every participant speech |
| `round_end` | All participants have spoken in a round |
| `concluded` | Discussion ends |

### Configuration

```python
notifications = {
    "enabled": True,
    "channels": [
        {"platform": "feishu", "chat_id": "oc_xxx"},
        {"platform": "slack", "chat_id": "#engineering"},
    ],
    "events": ["round_end", "concluded"],  # Subscribe to specific events
}
```

### Custom send function

The `send_fn` callback handles actual message delivery:

```python
def send_fn(platform: str, chat_id: str, message: str) -> None:
    # Your delivery logic here
    ...

core = RoundtableCore(send_fn=send_fn)
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

When installed alongside Hermes Agent, the adapter auto-registers all 9 tools:

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
├── notify.py         # Notifier — event-driven notification dispatch
└── adapters/
    ├── hermes.py     # Hermes Agent tool adapter
    └── generic.py    # Generic Python API (error-safe facade)
```

## Development

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Write tests for your changes
4. Ensure all tests pass (`pytest tests/ -v`)
5. Commit your changes (`git commit -m 'feat: add amazing feature'`)
6. Push to the branch (`git push origin feature/amazing-feature`)
7. Open a Pull Request

### Code style

- Python 3.10+ with type hints
- Zero external dependencies (stdlib only)
- All exceptions inherit from `RoundtableError` (which inherits `ValueError`)
- All public methods return JSON-serializable dicts

## Changelog

### v0.1.0 (2026-05-21)

- Initial release
- Core discussion engine (SQLite-backed)
- Multi-round structured discussions with convergence tracking
- Notification system with pluggable send_fn
- Generic adapter (error-safe facade)
- Hermes Agent adapter (auto-registration)
- 9 operations: init, speak, read, status, summarize, end, list, advance, notify

## License

MIT
