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

> [!CAUTION]
> **⚠️ CRITICAL RULE FOR AGENTS**: The Direct Core API (importing and executing `RoundtableCore` directly) is a private backend code interface reserved exclusively for human developer troubleshooting. Agents are **STRICTLY PROHIBITED** from executing Direct Core API scripts or bypasses in terminal environments. All agents **must** use the standard platform tools: `roundtable_init`, `roundtable_speak`, `roundtable_read`, and `roundtable_end` via standard platform tool call invocations. Never attempt to run local Python scripts importing `RoundtableCore` or `_get_core()`.


# Roundtable Discussion Skill

## Publishing to skill hubs

When preparing Roundtable for Hermes Skill Hub or OpenClaw/ClawHub, use the release checklist in `references/skill-hub-publishing.md`. Key reminders: keep `src/skills/` self-contained and free of private team data, include both Hermes and OpenClaw metadata blocks in `SKILL.md`, check `hermes skills publish --help`, `clawhub publish --help`, and `clawhub whoami`, and gate real publishing on user confirmation of target account/repo.

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

Optionally send opening notification (only if notifications are NOT automatically configured via roundtable_init):
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

**3c. After each participant, send notification (only if notifications are NOT automatically configured via roundtable_init):**
```
send_message(target="feishu:oc_xxx", message="💬 Round {N} | {role} ({display_name}) spoke:\n{summary}")
```

**3d. After all participants in a round, send round_end notification (only if notifications are NOT automatically configured via roundtable_init):**
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

Send concluded notification (only if notifications are NOT automatically configured via roundtable_init):
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

### Automatic vs. Manual Notification Rule
- **Automatic Mode**: When `notifications` config is passed to `roundtable_init` with `"enabled": True`, the platform tool calls automatically trigger Feishu notifications on events (round_start, speech, round_end, concluded). In this mode, the coordinator agent **must NOT** send manual duplicate notifications via `send_message`.
- **Manual Mode (Fallback)**: If `notifications` are not enabled in `roundtable_init`, the coordinator may manually call `send_message` after important milestones to notify the group chat.

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

The format below works for general discussions. For **product/design/dev discussions aimed at producing a buildable specification**, use the decision-oriented format instead — see `references/web-viewer-discussion-example.md` for the full pattern (MVP scope, tech architecture, acceptance criteria, risk assessment, design deliverables, action items).

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

## Gotchas & Crucial Details

1. **At least 2 participants required** — A discussion needs multiple viewpoints.
2. **Participant registration** — Only profiles listed in `participants` can speak. **Exception**: The `coordinator` is always allowed to speak in round 0 and to write summaries, and does not affect round advancement logic.
3. **Round 0 is opening** — Coordinator speaks first, then round 1 begins.
4. **Auto-conclude on max_rounds** — The discussion ends automatically when the maximum number of rounds is reached.
5. **No LLM in summarize** — `roundtable_summarize` returns raw JSON data, NOT a summary. The coordinator must manually write the conclusion document based on this data.
6. **Round Advancement (`roundtable_advance`)** — While rounds automatically advance when all participants have spoken, you can natively invoke `roundtable_advance` to manually advance the round if needed.
7. **Sequential delegation, not parallel** — Delegate to participants one at a time so they can read and build on each other's responses. Parallel delegation results in participants speaking without context.
8. **Write conclusion doc BEFORE roundtable_end** — The `roundtable_end` tool only accepts a brief summary text. Write and save the full conclusion document (via `write_file`) before ending the discussion.
9. **WebViewer integration** — Setting `web=True` on `roundtable_init` automatically starts the WebViewer. It is supported across processes.
10. **Notifications config** — Ensure you pass the `notifications` configuration parameter to `roundtable_init` if you want events to sync to messaging groups (e.g. Feishu). The adapter handles `send_fn` wiring automatically.
11. **Developer Reference** — For direct Python Core API references, venv configurations, or cross-process sync implementation details, see the separate developer reference guide at [developer-guide.md](file:///Users/parsifal/Repo/Monorepo/agent-roundtable/src/skills/references/developer-guide.md).

## Test Results

See `references/test-results-2026-05-20.md` for the first functional test results, including bugs found and product acceptance report.

## Open-Source Release

See `references/open-source-readiness.md` for the pre-release checklist (LICENSE, cleanup, adapter gaps, test isolation).

## Working Examples

- `references/opc-experience-discussion-example.md` — 4-round, 4-participant discussion with timing data and workflow
- `references/notifications-example.md` — roundtable with real-time push notifications to Feishu
- `references/release-planning-discussion.md` — 3-round product/design/dev discussion for open-source release planning
- `references/ai-relay-open-source-discussion.md` — 3-round discussion with standard tool workflow, notifications, and conclusion doc → 5/29 release plan
- `references/web-viewer-discussion-example.md` — Decision-oriented conclusion doc pattern: MVP scope, tech architecture, acceptance criteria, risk assessment, design deliverables. Use this format when the discussion goal is to produce a buildable specification.
- `references/post-discussion-kanban-dispatch.md` — After discussion concludes, create kanban tasks grouped by owner, subscribe notifications, and dispatch to team via Feishu groups.

## Open-Source Release Checklist

See `references/open-source-readiness-checklist.md` for the pre-release audit: missing LICENSE, Hermes-specific files to separate, build-backend fix, .gitignore, internal docs to remove, generic adapter gaps, and target package structure.
