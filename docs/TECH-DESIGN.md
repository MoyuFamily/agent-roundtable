# Technical Design: Roundtable Skill Independence

## Problem Statement

The roundtable discussion skill was deeply coupled to Hermes Agent:
- Code lived in `~/.hermes/hermes-agent/tools/` and `hermes_cli/`
- Depended on Hermes' tool registration mechanism
- Depended on Hermes' `hermes_constants` and `hermes_state` modules
- The standalone repo was just a copy of the Hermes-internal code

## Solution: Layered Decoupling

### Architecture

```
┌─────────────────────────────────────┐
│         Adapter Layer               │
│  hermes.py │ generic.py │ langchain │
├─────────────────────────────────────┤
│         Core Layer                  │
│  RoundtableCore (business logic)    │
├─────────────────────────────────────┤
│         Storage Layer               │
│  RoundtableDB (SQLite, WAL mode)    │
├─────────────────────────────────────┤
│         Model Layer                 │
│  Discussion, Speech, Participant... │
└─────────────────────────────────────┘
```

### Decoupling Points

| Original Dependency | New Solution |
|---|---|
| `hermes_constants.get_hermes_home()` | `ROUNDTABLE_DB` env var → `~/.roundtable/roundtable.db` |
| `hermes_state.apply_wal_with_fallback()` | Inline `PRAGMA journal_mode=WAL` |
| `tools.registry.registry` | Adapter's `register_roundtable_tools()` function |
| `tools.registry.tool_error` | `json.dumps({"error": msg})` |
| `hermes_cli.config.load_config` | Adapter check function (optional) |
| Handler functions `_handle_*` | `RoundtableCore` methods |
| `from hermes_cli import roundtable_db` | `from roundtable.db import RoundtableDB` |

### Key Design Decisions

1. **RoundtableDB as a class** (not module-level functions) — enables multiple
   DB instances with different paths, easier testing, no global state.

2. **Exceptions inherit ValueError** — backward compatible with code that
   catches `ValueError` (including existing tests).

3. **Core returns dicts** — JSON-serializable results, no framework-specific
   types. Adapters just serialize/deserialize.

4. **Zero external dependencies** — only stdlib. Optional pydantic support
   can be added later.

5. **Auto-registration** — the Hermes adapter auto-registers when imported
   by Hermes' tool discovery, but doesn't fail if Hermes isn't present.

### Migration Path

1. **Hermes side**: Replace `tools/roundtable_tools.py` with a thin import:
   ```python
   from roundtable.adapters.hermes import *
   ```

2. **Tests**: Both old (Hermes-coupled) and new (independent) tests pass
   simultaneously. Old tests can be removed after migration.

3. **DB path**: Existing `~/.hermes/roundtable.db` works — set
   `ROUNDTABLE_DB=~/.hermes/roundtable.db` or let the Hermes adapter
   configure it.

### Test Coverage

- 27 DB layer tests (schema, CRUD, speeches, findings, convergence)
- 17 core layer tests (create, speak, read, status, end, list, summarize)
- 44 Hermes integration tests (backward compatibility)
- Total: 88 tests, all passing
