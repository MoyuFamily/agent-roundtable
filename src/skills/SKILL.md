---
name: agent-roundtable
description: "Multi-agent roundtable discussion — topic-driven multi-round debate with convergence detection and conclusion generation"
version: 2.1.0
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

Before publishing to Hermes Skill Hub or OpenClaw/ClawHub, run the repository release preflight and keep the skill package self-contained. Do not include repository-only notes, incident writeups, private chat transcripts, or secret-handling history in the public skill bundle. Confirm the target account/repository before running a real publish.

## Overview

Enable multiple agents to participate in structured, multi-round discussions
around a topic. Each participant is a **real sub-agent** spawned via
`delegate_task` — not the main agent role-playing. Each gets its own
conversation context, model call, and toolset.

**Core value**: Turn "one agent working alone" into "a team having a meeting."

Two complementary modes:

- **Single-process mode** (this document) — one coordinator agent spawns sub-agents via `delegate_task`. Best when one platform owns the whole discussion.
- **MCP Multi-Platform mode** (see below) — coordinator and participants live in *different* CLIs / IDEs (Claude Code, Cursor, Windsurf, Codex, WorkBuddy, …) and join the same roundtable through a shared MCP server.

## MCP Multi-Platform Mode

Bring agents from **different platforms** into one roundtable. Any MCP-capable agent can act as coordinator; participants join via invitations and speak when their turn arrives. State is shared through a SQLite database, so the same discussion is visible to every connected agent in real time.

**Install**

```bash
python3 -m roundtable.skills.mcp-roundtable.install --platform=auto
```

This auto-detects Claude Code / Cursor / Windsurf and writes the MCP config using the current Python interpreter path. Or add it manually:

```json
{
  "mcpServers": {
    "roundtable": {
      "command": "python3",
      "args": ["-m", "roundtable.mcp"]
    }
  }
}
```

For Codex or WorkBuddy (no native MCP), the easiest path is the built-in Codex entry point:

```bash
python3 -m roundtable.codex
```

If you want to embed it in Python directly, run a bridge alongside:

```python
# Codex
from roundtable.mcp.bridges.codex import CodexBridge
CodexBridge(agent_id="codex-local").start()

# WorkBuddy / any HTTP-capable platform
from roundtable.mcp.bridges import GenericBridge
GenericBridge(agent_id="workbuddy-1", platform="workbuddy", port=8202).start()
```

**Coordinator flow**

1. `roundtable_register_agent(agent_id, platform, display_name)` — announce yourself
2. `roundtable_list_agents(online_only=true)` — see who's around
3. `roundtable_create(topic, participants, invite_agents)` — open the discussion and invite others
4. `roundtable_speak(discussion_id, "coordinator", "...")` — opening statement
5. `roundtable_status(discussion_id)` / `roundtable_summarize(discussion_id)` — monitor and synthesize
6. `roundtable_end(discussion_id, conclusion="...")` — close it out

**Participant flow**

1. `roundtable_register_agent(agent_id, platform)` — announce yourself
2. Poll `roundtable_inbox(agent_id)` (or subscribe to `roundtable://discussions`) — wait for invitations and turn notices
3. `roundtable_accept_invite(discussion_id, agent_id)` — join the discussion
4. `roundtable_wait_for_turn(discussion_id, agent_id, wait_seconds=30)` — wait briefly for your turn, or omit `wait_seconds` for an immediate state check
5. `roundtable_speak(discussion_id, your_profile, content)` — contribute

**Live updates** — subscribe to `roundtable://discussions/{id}` to receive `notifications/resources/updated` events whenever a speech is added, a round completes, or the discussion ends. No polling required.

See `docs/architecture.md` for the full tool list (15 tools), resource URIs, prompt templates, and deployment forms.

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
# Wait for completion; optionally notify only in manual mode, then delegate to participant 2
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

`roundtable_init` / `create_discussion` default to `web=True`. The Web Viewer is best-effort: discussion creation should still succeed when Node.js is missing, npm dependencies cannot be installed, or the viewer port is unavailable.

Returned fields:

- `web_status`: `ready`, `failed`, or `disabled`
- `web_url`: viewer URL when ready, otherwise `None`
- `web_error` and `web_help`: clear diagnostics for viewer startup failures

Startup order: reuse a healthy local viewer, start `node server.mjs`, optionally install local npm dependencies with `npm install --omit=dev`, then retry. PM2 is optional only. Roundtable never installs Node itself and never performs silent global npm installs.

Browser opening is adapter-level UX. Core and generic APIs return the URL and status fields; headless environments should read those fields instead of assuming a browser window exists.

### Iframe Embed Mode

The web viewer supports an embed mode optimized for iframe contexts:

```
GET /embed/<token>
```

- Renders a compact view: no header chrome, no share/export/revoke buttons, no replay controls
- Reuses the same token validation, password gate, and expiration checks as `/r/:token`
- Password-protected discussions show a "open in new tab" prompt instead of inline password form
- Sends `Content-Security-Policy: frame-ancestors *` to allow cross-origin embedding
- Real-time SSE streaming works identically to the full viewer

Recommended iframe attributes:
```html
<iframe src="https://roundtable.izmw.me/embed/<token>"
  width="100%" height="600" frameborder="0"
  style="border:1px solid #334155;border-radius:12px"
  sandbox="allow-scripts allow-same-origin allow-popups">
</iframe>
```

The share popover in the full viewer includes a "复制嵌入代码" button that generates this snippet automatically.

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

The format below works for general discussions. For **product/design/dev discussions aimed at producing a buildable specification**, prefer a decision-oriented format with MVP scope, technical architecture, acceptance criteria, risk assessment, design deliverables, and action items.

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
11. **Developer Reference** — Maintainer-only implementation documentation exists separately and is not part of the agent execution workflow.
