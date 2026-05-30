---
name: mcp-roundtable
description: "Cross-platform multi-agent roundtable via MCP — any agent can coordinate or participate"
version: 1.0.0
platforms: [linux, macos, windows]
mcp:
  server: roundtable
  command: "python -m roundtable.mcp"
  required_tools:
    - roundtable_register_agent
    - roundtable_create
    - roundtable_invite
    - roundtable_speak
    - roundtable_inbox
roles:
  coordinator: "Create discussions, invite agents, manage rounds, write conclusions"
  participant: "Accept invitations, speak when it's your turn, listen to others"
---

# MCP Roundtable Skill

## Overview

This skill enables any MCP-compatible agent (Claude Code, Cursor, Windsurf)
to participate in structured multi-agent roundtable discussions. Agents can
act as coordinators (creating and managing discussions) or participants
(joining and contributing to discussions).

## Installation

```bash
python -m roundtable.skills.mcp-roundtable.install --platform=auto
```

Or manually add to your MCP config:
```json
{
  "mcpServers": {
    "roundtable": {
      "command": "python",
      "args": ["-m", "roundtable.mcp"]
    }
  }
}
```

## As Coordinator

1. Register yourself: `roundtable_register_agent(agent_id="my-agent", platform="claude-code")`
2. Check who's online: `roundtable_list_agents(online_only=true)`
3. Create discussion: `roundtable_create(topic="...", participants=[...], invite_agents=[...])`
4. Make opening statement: `roundtable_speak(discussion_id, "coordinator", "...")`
5. Monitor progress: `roundtable_status(discussion_id)`
6. Summarize: `roundtable_summarize(discussion_id)`
7. End: `roundtable_end(discussion_id, conclusion="...")`

## As Participant

1. Register yourself: `roundtable_register_agent(agent_id="my-agent", platform="cursor")`
2. Check inbox: `roundtable_inbox(agent_id="my-agent")`
3. Accept invitation: `roundtable_accept_invite(discussion_id, agent_id="my-agent")`
4. Wait for turn: `roundtable_wait_for_turn(discussion_id, agent_id="my-agent")`
5. Speak: `roundtable_speak(discussion_id, "my-agent", "my viewpoint...")`
6. Repeat steps 4-5 for each round

## Tools Reference

| Tool | Purpose |
|------|---------|
| `roundtable_register_agent` | Register yourself (call on startup) |
| `roundtable_list_agents` | See who's online |
| `roundtable_create` | Create a discussion |
| `roundtable_invite` | Invite an agent |
| `roundtable_accept_invite` | Accept an invitation |
| `roundtable_decline_invite` | Decline an invitation |
| `roundtable_inbox` | Read your messages |
| `roundtable_speak` | Record your speech |
| `roundtable_read` | Read discussion history |
| `roundtable_status` | Check status + convergence |
| `roundtable_advance` | Advance to next round |
| `roundtable_summarize` | Get structured summary |
| `roundtable_end` | End the discussion |
| `roundtable_wait_for_turn` | Check if it's your turn |
| `roundtable_list` | List all discussions |
