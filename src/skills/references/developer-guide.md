# Roundtable Developer & Debugging Guide

This document is intended for human developers and maintainers of the `agent-roundtable` package. It details private/internal APIs, environment bootstrapping, and implementation details of the cross-process data synchronization mechanism.

> [!WARNING]
> **This guide is for human developer troubleshooting only.** Agents are strictly prohibited from bypassing standard platform tools or running python scripts using the APIs documented below during execution.

---

## 1. Direct Core API (Developer Troubleshooting Only)

In headless environments or for debugging adapter/tool layer issues, developers can interact with the core roundtable engine directly using Python scripts.

### 1.1 Importing the Core Singleton
Always retrieve the core instance using the `_get_core()` helper from the tool wrapper module to ensure notifications are wired correctly:

```python
import sys
sys.path.insert(0, "/Users/parsifal/.hermes/hermes-agent")
from tools.roundtable_tools import _get_core

core = _get_core()
```

> [!CAUTION]
> Do NOT import `RoundtableCore` directly (e.g. `from roundtable.core import RoundtableCore`), as this bypasses crucial notification and adapter wiring.

### 1.2 Direct API Examples

#### Creating a Discussion
```python
participants = [
    {"profile": "bingge", "role": "Product Director", "display_name": "Bing"},
    {"profile": "mafei", "role": "Tech Lead", "display_name": "Fei"},
]
res = core.create_discussion(
    topic="My Debugging Topic",
    participants=participants,
    web=True,
    web_port=8199
)
print("Created discussion:", res["discussion_id"])
print("WebViewer URL:", res["web_url"])
```

#### Recording a Speech
```python
result = core.speak(
    discussion_id="rt_xxxxxxxx",
    participant="bingge",
    content="This is recorded directly via Core API."
)
print("Speech recorded. Next speaker:", result.get("next_speaker"))
```

#### Ending the Discussion
```python
core.end_discussion(
    discussion_id="rt_xxxxxxxx",
    conclusion="Debugging completed successfully."
)
```

---

## 2. Environment Setup & Bootstrapping

### 2.1 Installing in Hermes Runtime Venv
To enable direct Python invocations in standard Hermes environments, bootstrap pip and install the roundtable package:

```bash
# Bootstrap pip in hermes-agent venv
~/.hermes/hermes-agent/venv/bin/python3 -m ensurepip
# Install roundtable package in editable mode
~/.hermes/hermes-agent/venv/bin/python3 -m pip install /path/to/roundtable
```

### 2.2 Alternative: Isolated Venv via `uv`
If system Python is outdated (<3.10) or hermes venv lacks pip, set up a dedicated environment using `uv`:

```bash
# Create venv with Python 3.12
uv venv /tmp/roundtable-venv --python 3.12
# Install roundtable
uv pip install -e /path/to/roundtable --python /tmp/roundtable-venv/bin/python3
```

---

## 3. Cross-Process WebPublisher Sync Mechanism

Because each tool invocation (`roundtable_init`, `roundtable_speak`, `roundtable_end`) runs in an independent Python process, the in-memory state of `RoundtableCore` is not preserved between calls. The WebPublisher's HTTP Express server is kept running by PM2, but the Python publisher object is lost.

### 3.1 Fallback Sync Methods
To keep the WebViewer updated, two fallback methods are implemented in `core.py`:
1. `_update_web_discussion_json()`: Reads `discussion.json` from disk under flock, appends the new speech and corresponding `speech_delta` event, writes to a `.tmp` file, and atomizes via `os.rename()`.
2. `_conclude_web_discussion()`: Sets status to concluded and appends `status_delta` event.

### 3.2 Lock File Protocol
To avoid race conditions where concurrent writes or a lagging live publisher overwrite new data, both `core.py` and `web_publisher.py` must acquire an exclusive lock on `discussion.json.lock` using `fcntl.flock(lock_file, LOCK_EX)` before reading, merging, or writing.

### 3.3 High-Precision float timestamps
To determine the ordering of concurrent/delayed updates, `final_summary` uses float timestamps (`time.time()`). When merging data, the newer timestamp on disk always takes precedence over stale in-memory state.

---

## 4. Internal Notification Wiring & Debugging

The automatic notification system requires a `send_fn(platform, chat_id, message)` callback configured on the `RoundtableCore` singleton. The Hermes adapter (`adapters/hermes.py`) provides `_hermes_send_fn` which launches `feishu-send.py` via a subprocess (incurring ~1-2s overhead per notification).

### 4.1 Verifying send_fn Wiring
If `send_fn` is not wired correctly, notifications are silently disabled and the Notifier's `enabled` check returns `False`.
You can verify this in Python with:
```python
assert core._send_fn is not None, "Notification callback is not wired!"
```

### 4.2 Logging Notification Subprocess Calls
To debug issues where notifications appear to not fire, wrap the `send_fn` callback with logs to verify its execution:
```python
original_send = core._send_fn
def debug_send_fn(platform, chat_id, message):
    print(f"[DEBUG SEND] platform={platform}, chat={chat_id}, msg_len={len(message)}")
    original_send(platform, chat_id, message)
    print(f"[DEBUG SEND] OK")
core._send_fn = debug_send_fn
```

---

## 5. Multiple Database Isolation

Different runtime environments may write to different database paths:
- `~/.roundtable/roundtable.db` — Main agent discussions.
- `~/.hermes/roundtable.db` — Hermes tool-layer discussions.
- `~/.hermes/profiles/{profile}/home/.roundtable/roundtable.db` — Isolated sub-agent discussions.

Ensure you inspect or query the correct database file depending on the active profile/runtime context.
