---
name: agent-roundtable
description: "Multi-agent roundtable discussion — topic-driven multi-round debate with convergence detection and conclusion generation"
version: 1.2.4
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [discussion, multi-agent, collaboration, debate, roundtable]
    related_skills: [kanban-worker, kanban-orchestrator]
  openclaw:
    requires:
      env: []
      bins: []
    primaryEnv: null
    emoji: "🤝"
    homepage: "https://roundtable.izmw.me"
---

# Roundtable Discussion Skill

## Publishing to skill hubs

When preparing Roundtable for Hermes Skill Hub or OpenClaw/ClawHub, use the release checklist in `src/skills/references/skill-hub-publishing.md`. Key reminders: keep `src/skills/` self-contained and free of private team data, include both Hermes and OpenClaw metadata blocks in `SKILL.md`, check `hermes skills publish --help`, `clawhub publish --help`, and `clawhub whoami`, and gate real publishing on user confirmation of target account/repo.

## Overview

Enable multiple agents to participate in structured, multi-round discussions
around a topic. Each participant is a **real sub-agent** spawned via
`delegate_task` — not the main agent role-playing. Each gets its own
conversation context, model call, and toolset.

**Core value**: Turn "one agent working alone" into "a team having a meeting."

## When to Use

- **Tech design review**: product, frontend, backend, architect debate approach
- **Competitive analysis**: product, marketing, design compare alternatives
- **Bug root cause analysis**: backend, ops, test triangulate the issue
- **Product requirements**: product, design, dev align on scope
- **Architecture decisions**: architect, backend, frontend, devops choose stack

## Prerequisites

Enable the `roundtable` toolset in the profile config:

```yaml
toolsets:
  - roundtable
```

Or pass `enabled_toolsets: ["roundtable"]` when spawning an agent.

## Tools

| Tool | Purpose |
|------|---------|
| `roundtable_init` | Create a discussion with topic + participants (+ optional notifications config) |
| `roundtable_speak` | Record a participant's speech (auto-triggers notifications if configured) |
| `roundtable_read` | Read discussion history |
| `roundtable_status` | Check status + convergence metrics |
| `roundtable_summarize` | Get structured data for conclusion doc (use `compact=true` for smaller output) |
| `roundtable_end` | Conclude or cancel a discussion (triggers concluded notification) |
| `roundtable_list` | List all discussions |
| `roundtable_advance` | Manually advance to next round (use when auto-advance doesn't trigger) |
| `roundtable_notify` | Manually trigger a notification event for a discussion |

## Execution Model (Important)

Each participant is a **real, independent sub-agent**:

1. Coordinator calls `delegate_task(goal=..., toolsets=["roundtable"])` for each participant
2. The sub-agent runs its own model inference with its own context window
3. The sub-agent calls `roundtable_speak(participant="{profile}", ...)` to record its speech
4. The sub-agent returns a summary to the coordinator
5. Coordinator sends notification (optional), then delegates to next participant

**This means**: 4 participants × 4 rounds = 16 `delegate_task` calls = 16 independent
model invocations. Expect ~15-20 minutes for a full discussion. Each participant
takes 15-60 seconds per round depending on context size and model speed.

## Coordinator Flow

### Step 1: Create the Discussion

```
roundtable_init(
    topic="Database selection: PostgreSQL vs MySQL vs TiDB",
    context="Our e-commerce system needs high-concurrency read/write, 1TB+ data",
    participants=[
        {"profile": "bingge", "role": "Product Director", "perspective": "Focus on UX", "display_name": "Bing"},
        {"profile": "mafei", "role": "Tech Lead", "perspective": "Focus on feasibility", "display_name": "Fei"},
        {"profile": "xiaosu", "role": "Designer", "perspective": "Focus on data display", "display_name": "Su"},
    ],
    created_by="coordinator",  # optional: identifies the discussion creator
    max_rounds=3,
    speech_order="fixed",
    notifications={
        "enabled": True,
        "channels": [
            {"platform": "feishu", "chat_id": "oc_xxx"},
        ],
        "events": ["round_start", "speech", "round_end", "concluded"],
    }
)
→ returns {discussion_id, ...}
```

**Notifications** (optional): pushes real-time discussion updates to messaging
channels. See [Notifications](#notifications) section below.

### Step 2: Opening Statement (Round 0)

```
roundtable_speak(
    discussion_id="rt_xxxxxxxx",
    participant="coordinator",
    content="Today we're discussing database selection..."
)
```

Optionally send opening notification:
```
send_message(target="feishu:oc_xxx", message="🔔 Roundtable started [rt_xxx]\n📋 Topic: ...\n👥 Participants: ...")
```

### Step 3: Multi-Round Discussion

For each round:

**3a. Coordinator summarizes previous round (optional but recommended):**
```
roundtable_speak(
    discussion_id="rt_xxxxxxxx",
    participant="coordinator",
    content="Round N summary: key points, emerging consensus, open questions..."
)
```

**3b. Delegate to each participant SEQUENTIALLY (not parallel):**

```python
delegate_task(
    goal="You are {display_name}, {role}. Share your viewpoint on this topic from a {role} perspective, then call roundtable_speak to record your speech.",
    context="""You are participating in a roundtable discussion.

## Discussion Info
- Topic: {topic}
- Context: {context}
- Current Round: Round {N} / {max_rounds}
- Your Role: {role} ({display_name})
- Your Perspective: {perspective}

## Discussion History
{formatted_history}

## Your Task
From your role's perspective, share your viewpoint on this topic.
- Reference others' points if relevant
- Keep it 200-500 words
- Both pros AND cons, with concrete examples

After speaking, call roundtable_speak to record your statement:
roundtable_speak(discussion_id="{id}", participant="{profile}", content="your speech")""",
    toolsets=["roundtable"]
)
# Wait for completion, then send notification, then delegate to participant 2
```

**3c. After each participant, send notification (if configured):**
```
send_message(target="feishu:oc_xxx", message="💬 Round {N} | {role} ({display_name}) spoke:\n{summary}")
```

**3d. After all participants in a round, send round_end notification:**
```
send_message(target="feishu:oc_xxx", message="✅ Round {N} complete\nConsensus: ...\nDisagreements: ...")
```

**Why sequential, not parallel**: Participants need to read each other's responses to build on them. Parallel delegation means everyone speaks into a void.

### Step 4: Check Convergence

After each round:
```
roundtable_status(discussion_id="rt_xxxxxxxx")
→ check convergence_score, consensus_points, disagreement_points
```

**Note**: Convergence tracking may not work reliably due to the round-tracking bug. The coordinator should manually assess convergence from the discussion content.

### Step 5: Generate Conclusion

```
summary = roundtable_summarize(discussion_id="rt_xxxxxxxx")
```

**⚠️ WARNING**: `roundtable_summarize` returns the ENTIRE discussion as raw JSON — potentially 100KB+. It does NOT generate a summary. The coordinator must:
1. Read the summary data (use `read_file` with offset/limit for the persisted output)
2. Write the conclusion document themselves based on the discussion content
3. Save to the `output_path` specified during init (or write manually via `write_file`)

**Important**: Write the conclusion doc BEFORE calling `roundtable_end` — the end call only accepts a brief text string, not a full document.

### Step 6: End Discussion

```
roundtable_end(
    discussion_id="rt_xxxxxxxx",
    conclusion="Brief text summary of the conclusion"
)
```

Send concluded notification:
```
send_message(target="feishu:oc_xxx", message="🏁 Discussion ended\nConclusion: ...")
```

## Participant Prompt Template

When delegating to a participant sub-agent, use this template:

```
You are participating in a roundtable discussion.

## Discussion Info
- Topic: {topic}
- Context: {context}
- Current Round: Round {current_round} / {max_rounds}
- Your Role: {role} ({display_name})
- Your Perspective: {perspective}

## Discussion History
{formatted_history}

## Your Task
From your role's perspective, share your viewpoint on this topic.
- You may reference or respond to other participants' statements
- Keep it concise and powerful, 200-500 words
- If you agree with a point, explicitly state your agreement
- If you disagree, explain why and propose alternatives

After speaking, call roundtable_speak to record your statement.
```

## Notifications

Push real-time discussion updates to messaging channels.

### Configuration

```python
roundtable_init(
    topic="...",
    participants=[...],
    notifications={
        "enabled": True,
        "channels": [
            {"platform": "feishu", "chat_id": "oc_xxx"},
        ],
        "events": ["round_start", "speech", "round_end", "concluded"]  # default: all
    }
)
```

### Events

| Event | Trigger | Content |
|-------|---------|---------|
| `round_start` | First speech in a new round | Round number + previous round summary |
| `speech` | After each participant speaks | Speaker name/role + content (truncated to 200 chars) |
| `round_end` | All participants spoke in a round | Key points + convergence score |
| `concluded` | Discussion ends | Final conclusion + consensus/disagreement points |

### send_fn Requirement

The notification system requires a `send_fn(platform, chat_id, message)` callback
on `RoundtableCore`. The Hermes adapter (`adapters/hermes.py`) provides
`_hermes_send_fn` which calls `feishu-send.py` via subprocess.

**If send_fn is not wired**, notifications are silently disabled — the Notifier's
`enabled` returns `False`. Verify with: `core._send_fn is not None`.

**Manual fallback**: If send_fn is broken or unavailable, the coordinator can
manually push notifications using `send_message` after each speech:
```
send_message(target="feishu:oc_xxx", message="💬 Round {N} | Speaker: summary...")
```

### Timing

With automatic notifications (send_fn wired), each speech triggers a subprocess
call to feishu-send.py (~1-2s overhead). With manual `send_message`, overhead is
similar but requires explicit coordinator action after each speech.

### Verifying Notifications (Pitfall)

**Feishu API returns messages in chronological order by default** (oldest first).
When checking if roundtable notifications arrived in the group chat, you MUST use
`sort_type=ByCreateTimeDesc` in the API call — otherwise you see old messages and
conclude (incorrectly) that notifications didn't send.

**Wrong** — default sort returns oldest messages first:
```python
resp = requests.get('https://open.feishu.cn/open-apis/im/v1/messages',
    params={'container_id': 'oc_xxx', 'page_size': 10})
```

**Correct** — sort descending to see latest messages:
```python
resp = requests.get('https://open.feishu.cn/open-apis/im/v1/messages',
    params={'container_id': 'oc_xxx', 'page_size': 10, 'sort_type': 'ByCreateTimeDesc'})
```

**Debug pattern**: If notifications appear to not fire, add a wrapper `send_fn`
with logging to confirm the callback is actually invoked:
```python
def debug_send_fn(platform, chat_id, message):
    print(f"[DEBUG SEND] platform={platform}, chat={chat_id}, msg_len={len(message)}")
    original_send(platform, chat_id, message)
    print(f"[DEBUG SEND] OK")
```

**Multiple roundtable.db files**: The system may have multiple databases:
- `~/.roundtable/roundtable.db` — main agent discussions
- `~/.hermes/roundtable.db` — hermes tool layer discussions
- `~/.hermes/profiles/{profile}/home/.roundtable/roundtable.db` — sub-agent discussions

Always verify against the correct DB when checking discussion state.

## Web Viewer (default ON)

`run_demo()` has `web: bool = True` by default (changed from `False`). This means demo discussions automatically start a web viewer at `http://localhost:8199`. The viewer uses PM2 to manage an Express subprocess, fcntl for file locking, and nanoid for token generation.

**Browser auto-open**: Starting a discussion with `web=True` should automatically open the browser via `subprocess.run(["open", web_url])` in the Hermes adapter's `_handle_init`. This is an **adapter-level side-effect**, not a core-level one — the core library returns the URL but leaves UX actions to the adapter. The generic adapter intentionally does NOT auto-open (headless environments). If you need to customize browser behavior (e.g., open in a specific browser), modify `_handle_init` in `adapters/hermes.py`.

**⚠️ Pitfall: Browser opens at END instead of START (2026-05-23)** — Boss reported the browser doesn't open when the discussion begins; it only opens after the discussion concludes (or manually). The `_handle_init` code has the `subprocess.run(["open", web_url])` call, but it may not fire reliably in all execution paths. **Diagnosis checklist**: (1) Verify `_handle_init` actually reaches the `subprocess.run` line (add logging) (2) Check if the `web_url` variable is correctly populated from `publisher.start()` return (3) Confirm the `open` command runs in the correct subprocess context (may need `shell=False` with list args on macOS). **See also**: Bug task `t_xxxxxxxx` for the specific fix.

**⚠️ Pitfall: WebViewer real-time updates broken on macOS (2026-05-23)** — Boss reported that the WebViewer doesn't show new speeches in real-time; the browser must be force-refreshed to see updates. **Root cause**: The Express server (`server.mjs`) uses `fs.watch(DISCUSSION_PATH, ...)` to detect `discussion.json` changes and broadcast via SSE. But Python's `WebPublisher` uses atomic write: `write .json.tmp → os.rename()`. On macOS, `fs.watch()` on a file loses tracking after `rename()` replaces the inode — the watcher stays on the old inode, never sees the new file's changes. **Fix**: Change `fs.watch` to watch the **directory** instead of the file, then filter by filename:
```javascript
// Wrong — breaks on atomic rename:
watch(DISCUSSION_PATH, () => { ... });

// Correct — watches directory, catches rename:
const dir = require("path").dirname(DISCUSSION_PATH);
const filename = require("path").basename(DISCUSSION_PATH);
watch(dir, (eventType, changedFilename) => {
  if (changedFilename !== filename) return;
  // ... debounce + broadcast logic unchanged
});
```
**Alternative**: Add server-side polling fallback (`setInterval` + mtime check) as defense-in-depth. **See also**: Bug task `t_xxxxxxxx` for the specific fix.

*Note: Tool calls executed natively on the platform handle environment and browser integration automatically.*

## Convergence Detection

Each round is evaluated for convergence:

| Metric | Formula | Meaning |
|--------|---------|---------|
| Consensus | Points multiple participants agree on | Alignment |
| Disagreement | Points participants disagree on | Conflict |
| New Point | New topics raised this round | Scope expansion |
| Score | consensus / (consensus + disagreement) | Overall alignment |

**Termination conditions:**
- Convergence score > 0.8 → high consensus, wrap up
- Max rounds reached → prevent infinite discussion
- Coordinator manually ends → emergency stop
- All participants vote to end → democratic close

## Conclusion Document Format

The format below works for general discussions. For **product/design/dev discussions aimed at producing a buildable specification**, use the decision-oriented format instead — see `src/skills/references/web-viewer-discussion-example.md` for the full pattern (MVP scope, tech architecture, acceptance criteria, risk assessment, design deliverables, action items).

```markdown
# Roundtable Conclusion: [Topic]

## Summary
- Participants: Product(Bing), Design(Su), Dev(Fei)
- Rounds: 3
- Date: 2026-05-20

## Consensus Points
1. [Point 1]
2. [Point 2]

## Disagreement Points
1. [Point 1] - Various perspectives

## Action Items
1. [ ] [Action 1] - Owner: xxx
2. [ ] [Action 2] - Owner: xxx

## Detailed Transcript
### Round 1
- **Product(Bing)**: ...
- **Design(Su)**: ...
- **Dev(Fei)**: ...

### Round 2
...
```

## Data Storage

- **Database**: `~/.hermes/roundtable.db` (independent from kanban.db)
- **Conclusion docs**: Configurable via `output_path`, defaults to project docs dir
- **ID format**: `rt_` + 8 hex chars (e.g., `rt_a1b2c3d4`)

## Integration with Kanban

Discussions can be linked to kanban tasks:

```
# After conclusion, add as task comment
kanban_comment(task_id="t_xxx", body="Roundtable conclusion: {conclusion_path}")
```

## Direct Core API (Developer Debugging Only — Agents Prohibited)

> **⚠️ CRITICAL RULE FOR AGENTS**: The Direct Core API (importing and executing `RoundtableCore` directly) is a private backend code interface reserved exclusively for human developer troubleshooting. Agents are **STRICTLY PROHIBITED** from executing Direct Core API scripts or bypasses in terminal environments. 
>
> All agents **must** use the standard platform tools: `roundtable_init`, `roundtable_speak`, `roundtable_read`, and `roundtable_end` via standard platform tool call invocations. Never attempt to run local Python scripts importing `RoundtableCore` or `_get_core()`.

24. **Quick verification meetings** — When Boss says "组织一次会议看效果", use the lightweight pattern: coordinator speaks for all participants directly via `roundtable_speak` (no `delegate_task`). Runs in ~2min vs ~15-20min. Always include notifications config even for demos — the goal is to verify the full pipeline including group chat sync. See `src/skills/references/quick-verification-example.md` for a working example.
25. **Standard Tool Invocations** — Ensure that `roundtable_init` and `roundtable_speak` are invoked natively through the platform's tool calling mechanism rather than command-line subprocesses to ensure correct profile contexts, event telemetry, and permission auditing.
26. **Emergency Bypass Prohibition** — Never write or execute custom Python wrappers or scripts to bypass standard tools. If a tool call fails, log the exception and report it as a bug task for human engineers to investigate.
27. **`web` and `web_port` params on roundtable_init** — The core supports `web=True` to auto-start a WebPublisher HTTP server. The Hermes tool schema now includes these params. Default `web=True` in `_handle_init` so discussions always open WebViewer. Port auto-increments if 8199 is busy (check `web_url` in init response for actual port).
28. **Adapter handles UX side-effects, core returns data** — When adding features that interact with the user's environment (browser, notifications, file watchers), implement them at the **adapter level** (`adapters/hermes.py`), not in `core.py`. The core library should be stateless and headless — it returns data (URLs, IDs, status) and the adapter decides what to do with it. Example: browser auto-open lives in `_handle_init` (adapter), not in `create_discussion` (core). The generic adapter may choose different UX behavior or none at all.
> **Notifications implementation detail**: See `src/skills/references/notifications-implementation.md` for architecture, send_fn wiring, and execution flow diagrams. See `src/skills/references/notification-debugging.md` for verification pitfalls and debugging checklist.

1. **At least 2 participants required** — A discussion needs multiple viewpoints
2. **Participant must be registered** — Only profiles listed in `participants` can speak. **Exception**: `participant="coordinator"` is always allowed (bypasses the participant check). This was a bug fix — previously, `roundtable_speak(participant="coordinator")` would fail with "not an active member". Coordinator's speech is recorded in round 0 and does NOT affect round advancement logic.
3. **Round 0 is opening** — Coordinator speaks first, then round 1 begins
4. **Auto-conclude on max_rounds** — Discussion ends automatically when max rounds exceeded
5. **Independent database** — roundtable.db is separate from kanban.db; don't mix paths
6. **No LLM in summarize** — `roundtable_summarize` returns raw JSON data (potentially 100KB+), NOT a summary. The coordinator must manually write the conclusion document. Use `read_file` with offset/limit to process the persisted output.
7. **connect() expects Path, not str** — Use `connect(Path("~/.hermes/roundtable.db"))`, not `connect("/Users/...")`
8. **delegate_task needs roundtable toolset** — Sub-agents spawned via `delegate_task` must have `enabled_toolsets=['roundtable']` to use roundtable tools
9. **Round tracking is buggy** — All speeches may end up as Round 0 regardless of actual round. The `round` field in speak responses may not reflect reality. Workaround: track rounds manually in the coordinator's logic.
10. **No `roundtable_advance` tool** — There is no tool to explicitly advance rounds. Rounds are supposed to auto-advance when all participants have spoken, but due to the round-tracking bug this may not work. The coordinator should track round progress manually.
11. **Sequential delegation, not parallel** — Delegate to participants one at a time so they can read each other's responses. Parallel delegation means everyone speaks without context.
12. **Coordinator summarizes between rounds** — After each round of participant speeches, the coordinator should call `roundtable_speak(participant="coordinator")` to summarize before delegating the next round. This gives participants context for their next response.
13. **summarize output is persisted as file** — When `roundtable_summarize` returns >8K chars, the full output is saved to a temp file. Use `read_file(path, offset, limit)` to process it in chunks.
14. **Hermes adapter send_fn must be wired** — The `adapters/hermes.py` creates `RoundtableCore()` without passing a `send_fn`, so notifications configured in `roundtable_init` will silently not send. Fix: implement `_hermes_send_fn(platform, chat_id, message)` that calls `feishu-send.py`, then pass it to `RoundtableCore(send_fn=_hermes_send_fn)`. Default profile should be `"default"` (not hardcoded to any specific profile). Without this fix, notifications are metadata only.
15. **Participants are real sub-agents, not role-play** — Each participant is a separate `delegate_task()` call that spawns an independent sub-agent with its own context window, model inference, and tool access. This is why a 4-round, 4-participant discussion takes 15-20 minutes (16+ independent model calls). The coordinator drives rounds sequentially so participants can read each other's responses.
16. **Generic adapter lacks notifications** — `adapters/generic.py` does not support `notifications` config or `send_fn`. Non-Hermes users must manually handle event dispatch. If releasing as standalone library, the generic adapter needs `send_fn` parameter support and `advance()` + `notify()` methods.
14. **send_fn must be wired in adapter** — The `Notifier` requires a `send_fn` callback to actually send messages. In `adapters/hermes.py`, `_get_core()` must pass `send_fn=_hermes_send_fn` to `RoundtableCore()`. Without this, notifications config is silently ignored (Notifier.enabled returns False). If notifications aren't firing, check that `_hermes_send_fn` is implemented and passed to the core. The send_fn uses `subprocess.run(["python3", script, profile, chat_id, message])` to call `feishu-send.py`.
15. **HERMES_PROFILE env var** — The send_fn reads `os.environ.get("HERMES_PROFILE", "default")` to determine which profile's Bot sends the notification. Default is `"default"` (coordinator). This is set automatically by the Hermes runtime — don't hardcode it.
16. **Real sub-agents, not role-playing** — Each participant in a roundtable discussion is a separate `delegate_task` call spawning an independent sub-agent with its own context window and model call. This is why 4 participants × 4 rounds = 16 delegate_task calls and ~15-20 minutes of runtime. If it were just the main agent role-playing, it would take seconds.
17. **Notifications don't block** — All notification failures are caught and logged. A broken send_fn never breaks the discussion flow. This is by design.
18. **Sub-agent context window** — Each participant sub-agent only sees what the coordinator passes in `context`. If you omit discussion history, the participant speaks "into a void". Always include `formatted_history` from `roundtable_read`.
19. **Write conclusion doc BEFORE roundtable_end** — `roundtable_end` only accepts a brief `conclusion` text string (1-2 sentences). The full conclusion document (with action items, tables, detailed transcript) must be written as a separate file via `write_file`. Do this BEFORE calling `roundtable_end` so you can still use `roundtable_summarize` if needed.
20. **Round numbering mismatch** — The `roundtable_summarize` output labels speeches as "Round 0", "Round 1", "Round 2" based on the DB's internal round counter. The coordinator's mental model (Round 1 = first participant round) may differ from the DB's (Round 0 = opening, Round 1 = first participant round). Always check the actual round field in the data rather than assuming.
21. **History reading cost grows linearly** — `roundtable_read` returns ALL speeches. In Round 3 of a 3-participant discussion, the first participant's `delegate_task` took 165s because the context included 9 full speeches. For longer discussions (4+ rounds, 4+ participants), consider summarizing previous rounds in the coordinator's `roundtable_speak` between rounds to keep context manageable.
22. **No convergence metrics in practice** — `roundtable_summarize` returns `final_convergence_score: null` and empty `consensus_points`/`disagreement_points`. The convergence detection is not implemented in the core engine. The coordinator MUST manually assess convergence from discussion content — don't rely on the status/summarize tools for this.
23. **Coordinator MUST pass notifications config** — Even though `send_fn` is wired in the adapter, `notifications` is an OPTIONAL parameter on `roundtable_init`. If you don't pass it, no events fire and no messages reach the group chat — silently. This is the #1 cause of "why didn't my discussion sync to the group?" Always include notifications when the discussion should be visible to the team. For OPC team, the standard config is: `notifications={"enabled": True, "channels": [{"platform": "feishu", "chat_id": "oc_your_company_group_id"}], "events": ["round_start", "speech", "round_end", "concluded"]}`. Without this explicit config, discussions run in "silent mode" — useful for testing, but almost never what you want in production.

## Cross-Process WebPublisher Data Sync (Critical Pitfall)

**Problem**: Hermes tool calls (`roundtable_init`, `roundtable_speak`, `roundtable_end`) each run in a **separate Python process**. The `_publishers` dict in `RoundtableCore` is in-memory — it's populated during `create_discussion()` in process A, but `speak()` runs in process B where `_publishers` is empty. Result: `publisher.on_speech()` is never called, `discussion.json` stays at `"speeches": []`, and the WebViewer shows nothing.

**Fix** (applied 2026-05-23): Two cross-process fallback methods in `core.py`:
- `_update_web_discussion_json()` — called in `speak()` when publisher not in memory; reads/writes `discussion.json` directly with fcntl locking
- `_conclude_web_discussion()` — called in `end_discussion()` when publisher not in memory; sets status="concluded" and writes conclusion

These methods find the JSON file at `/tmp/roundtable_web/{discussion_id}/discussion.json` and update it with the same atomic write pattern (flock → write .tmp → fsync → rename) that WebPublisher uses.

**Also fixed**: `publisher.conclude()` was called without the conclusion string argument — fixed to pass `disc_after.conclusion or ""`.

**Verification**: Tested with fully independent processes (create in process 1, 6 speeches each in separate processes, end in process 8). All 6 speeches appeared in WebViewer, conclusion displayed correctly.

**Impact**: Without this fix, the WebViewer is essentially non-functional in real Hermes usage since every tool call is a fresh process.

## Test Results

See `src/skills/references/test-results-2026-05-20.md` for the first functional test results, including bugs found and product acceptance report.

## Open-Source Release

See `src/skills/references/open-source-readiness.md` for the pre-release checklist (LICENSE, cleanup, adapter gaps, test isolation).

## Working Examples

- `src/skills/references/opc-experience-discussion-example.md` — 4-round, 4-participant discussion with timing data and workflow
- `src/skills/references/notifications-example.md` — roundtable with real-time push notifications to Feishu
- `src/skills/references/release-planning-discussion.md` — 3-round product/design/dev discussion for open-source release planning
- `src/skills/references/ai-relay-open-source-discussion.md` — 3-round discussion with standard tool workflow, notifications, and conclusion doc → 5/29 release plan
- `src/skills/references/web-viewer-discussion-example.md` — Decision-oriented conclusion doc pattern: MVP scope, tech architecture, acceptance criteria, risk assessment, design deliverables. Use this format when the discussion goal is to produce a buildable specification.
- `src/skills/references/post-discussion-kanban-dispatch.md` — After discussion concludes, create kanban tasks grouped by owner, subscribe notifications, and dispatch to team via Feishu groups.

## Open-Source Release

See `src/skills/references/open-source-readiness-checklist.md` for the pre-release audit: missing LICENSE, Hermes-specific files to separate, build-backend fix, .gitignore, internal docs to remove, generic adapter gaps, and target package structure.
# Test line
