---
name: agent-roundtable
description: "Organize professional roles for important decisions and Code Review; compare options, reconcile constraints, and retain evidence and dissent using host-run agents."
version: 2.1.0
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [decision-support, code-review, multi-agent, collaboration, roundtable]
    related_skills: [kanban-worker, kanban-orchestrator]
  openclaw:
    requires:
      env: []
      bins: []
    primaryEnv: null
    emoji: "🤝"
    homepage: "https://roundtable.izmw.me"
---

# Roundtable Decision Review Skill

## Purpose and boundaries

Help the user make important decisions with complementary professional roles.
Roles define responsibilities and deliverables; agents bring context and tools;
the host selects models for the actual tasks. Do not infer model identity from a
role name or claim that a model is always best for a profession.

Scenarios in scope: project direction, product scope and priorities, technical
choices, release/implementation, resources and business models, workflows and
tool selection, and Code Review. Validation may proceed in batches; Code Review
does not replace the other scenarios. These use a shared workflow, not seven
completed automation products. Simple fact lookup or an easily reversible
choice may need only one assistant.

The coordinator prepares the brief, assigns role tasks, focuses discussion, and
synthesizes options. The user makes the final decision. Assess professional
coverage, substantive analysis, and cross-role trade-offs.

The library records and formats the discussion. Team selection, model choice,
evidence gathering, and semantic synthesis remain host/coordinator responsibilities.
Do not promise automatic model routing, evidence verification, or finding extraction.

Use real participants when the host supports and authorizes delegation. If
independent execution is unavailable, disclose that limitation instead of
presenting one conversation as multiple independent agents. This skill grants
no additional permission to spawn agents, change code, merge, or send messages.

## Integration

Use the host's registered Roundtable tools. The Direct Core API is for developer
integration and troubleshooting; do not bypass missing platform tools with
terminal scripts or direct database writes during an agent review. Report the
missing integration and use a disclosed non-persisted review if appropriate.

- Managed review: the host executes role agents and records their contributions.
- Cross-platform review: participants share state through MCP or an HTTP bridge.

A meeting record does not start models. Arrange execution through the host and
honor its permissions, cost constraints, and available tools. Separate local
SQLite files do not become shared state merely by registering HTTP endpoints.

### Hermes

Enable the roundtable toolset in the profile, or include it when the host creates
an authorized participant:

~~~yaml
toolsets:
  - roundtable
~~~

### MCP and HTTP

From an installed, compatible source checkout, configure MCP with the installer:

~~~bash
python3 -m roundtable.skills.mcp-roundtable.install --platform=auto
~~~

For a host that needs HTTP access, the built-in bridge starts with:

~~~bash
python3 -m roundtable.codex
~~~

The bridge's /tool endpoint and /speak shortcut share speech handling and
next-turn notices. Retrieve review prompts with roundtable_get_prompt. Verify
resource subscriptions across the actual clients before relying on push alone;
status/inbox polling remains a fallback. For reliable processing, call
roundtable_inbox with mark_read=false, handle the returned message, then call
roundtable_ack_inbox with your agent_id and processed message_ids. Failed work
remains unread. The daemon only handles summon/invitation messages and leaves
turns for the host. Avoid multiple consumers executing the same task.

## Decision review workflow

### 1. Prepare the brief

Capture the decision owner, goals, constraints, options, available materials,
evidence gaps, and time/cost budget. Ask for missing information only when it
could change the choice. Distinguish facts, predictions, preferences, and unknowns.

### 2. Assign professional tasks

Choose roles needed for this question; templates are starting points. Assign
responsibilities, required materials, concrete questions, and deliverables to
each role. Identify missing coverage. Record actual agent/model assignments and
reasons when known; do not invent configuration or infer capability from a title.

An enterprise-edition review may need product (demand and scope), engineering
(implementation and maintenance), design (admin/member flows), and operations
(sales, delivery, and support). Change the team when the problem changes.

For resources/business models, consider product, business analysis, engineering,
and operations. Obtain budget, capacity, cost, and demand/usage evidence; compare
allocation or pricing options, assumptions, sensitivity, and pilot metrics.
For workflow/tool selection, include actual users, engineering, and the process
owner. Establish the current baseline and trial evidence; compare benefits with
migration, training, maintenance, and exit costs. Do not invent missing data or
reuse a template's default roles without checking their relevance.

### 3. Create and open the meeting

Use roundtable_init on Hermes or roundtable_create on MCP. Put the brief in
context and role tasks in each participant's perspective. Set a bounded number
of rounds and use the actual profiles supported by the host.

The coordinator must speak first as participant="coordinator" in round 0.
Normal participant analysis starts at round 1. Check returned errors before
continuing; do not claim a meeting was recorded when creation failed.

### 4. Analyze, then reconcile consequential conflicts

For an independent initial pass, give each agent the shared brief and role task
without peer conclusions. The host must separate contexts: this is a workflow
convention, not database access isolation. Analysis may run in parallel where
supported and authorized; record speeches in the configured order.

In response turns, provide relevant contributions and ask roles to address
conflicts, cite speech IDs, revise assumptions, or propose alternative and phased
options. Focus on issues that can change the choice rather than requiring every
role to repeat agreement.

Participant task:

~~~text
Role and responsibility: [assigned task]
Decision brief and source materials: [shared context]
Phase: [independent analysis or response]
Relevant peer contributions: [response phase only]

Compare feasible options within your responsibility. Give concrete benefits,
costs, constraints, evidence, and implications for other roles. State what
would change your judgment. Mark facts, assumptions, preferences, and unknowns.
In response turns, cite the relevant speech and explain revisions.
Check your turn, then record the analysis with roundtable_speak.
~~~

With fixed speaking order, submit in turn. Completed rounds advance automatically.
Use roundtable_advance only for an intentional skip, not after a completed round.
The host may use MCP participant_turn prompts: independent through round 1,
response afterwards, with an explicit phase override when needed. Tool-only and
HTTP hosts can obtain the same prompts with roundtable_get_prompt; prompt retrieval
does not run a model.

When the user corrects facts, read context_revision and call
roundtable_update_context with a complete revised brief, actual source, reason,
and expected_revision. Keep unaffected constraints and unknowns. Refresh role
prompts afterwards; do not leave the update only in a speech. Revisions preserve
history and do not consume turns. A concluded review needs a follow-up meeting
for new facts. current_round is an engine cursor; use total_rounds and
completed_rounds to report substantive progress.

### 5. Decide whether another round is useful

Check coverage, new information, unresolved constraints, and the agreed budget.
Stop when the decision can be framed usefully, further discussion adds little,
or the budget is exhausted. Preserve dissent. A high convergence score does not
establish completeness or correctness. The round limit automatically ends the
meeting but does not generate a professional recommendation.

### 6. Write and record the decision brief

Use roundtable_summarize(..., compact=true) for an overview. It is a formatted
record that may truncate speeches, not an LLM synthesis. Read full speeches with
roundtable_read before relying on consequential or excerpted statements.

The final brief should include:

- Decision, objectives, constraints, consulted roles, and missing perspectives.
- Feasible options with benefits, costs, dependencies, and conditions of use.
- Recommendation and rationale, citing supporting speeches or source material.
- Strongest remaining dissent, unverified assumptions, and information gaps.
- Validation or actions, suggested owners, and conditions for revisiting.
- Status: recommendation pending user decision, user-confirmed choice, or deferred.

Persist it with roundtable_end(..., conclusion="<decision brief>"). A conclusion
can be updated after automatic termination at the round limit. Verify the full
conclusion with roundtable_read or roundtable_summarize. Save a separate
full document when requested or needed by the existing workflow. Suggested owners
are not commitments; implementation and external notifications need authorization.

## Code Review

Code Review is a primary scenario. Establish expected behavior, base/head or a
specific diff, relevant code context, existing test results, and constraints.
The host provides repository access and tools; the template does not inspect code.

Choose correctness, architecture/maintainability, security, and testing/reliability
roles according to the change. Reduce the team for simple changes. Each reviewer
must inspect actual changes and relevant callers rather than a summary alone.

Each finding should identify file/line or symbol, trigger conditions, impact,
evidence or reproduction, severity with rationale, a suggested fix, and validation
status. Mark unverified hypotheses explicitly. Do not invent test runs or findings.

The coordinator deduplicates by root cause, reconciles conflicting findings, and
separates blockers, non-blocking suggestions, and unverified areas. Conclude with
a reasoned merge recommendation, changes-required recommendation, or insufficient
information. No findings does not prove safety; a recommendation does not merge a PR.

Evaluate confirmed findings, missed known defects, false positives, duplication,
reviewer time, and cost. Comment count or majority opinion is not review quality.

## Tools and state

| Purpose | Hermes | MCP |
|---|---|---|
| Create | roundtable_init | roundtable_create |
| Record/read | roundtable_speak / roundtable_read | Same |
| Inspect/summarize/end | roundtable_status / roundtable_summarize / roundtable_end | Same |
| Skip round/list | roundtable_advance / roundtable_list | Same |
| Registry/invite | Host-managed delegation | roundtable_register_agent / roundtable_list_agents / roundtable_invite |
| Join/turn | Host-managed scheduling | roundtable_accept_invite / roundtable_inbox / roundtable_wait_for_turn |

MCP also exposes heartbeat, summon, dispatch status, retry, decline, and explicit
inbox acknowledgement tools. Inbox message_types filters let different consumers
read only their own kinds of work. Legacy read-and-mark remains the default;
request mark_read=false when using process-then-ack.
Use the actual advertised schema rather than assuming parameters exist.

Findings are supplied externally. The engine calculates consensus divided by
consensus plus disagreement, or returns no score when annotations are absent.
MCP exposes roundtable_record_finding for explicit consensus, disagreement, or
new-point annotations with related_speeches from the same meeting. Verify the
referenced evidence before recording; the tool does not infer or validate the
judgment. Identical retries are deduplicated. Preserve dissent in the conclusion;
empty findings do not prove that participants agree.

The database is configured by the host or ROUNDTABLE_DB; Core defaults to
~/.roundtable/roundtable.db. An output_path is optional; without it, the conclusion
is retained in the discussion. Viewer startup is best effort: inspect web_status
and web_error. Viewer availability is separate from review quality.

## Notifications and downstream work

Only configure channels explicitly authorized by the user or existing workflow.
Automatic notification events include round_start, speech, round_end, and concluded;
do not send manual duplicates when automatic notifications are enabled.

Discussion recommendations do not authorize creating external tasks, messaging
people, implementing changes, or merging. Keep follow-up actions within the scope
already provided by the user. For configured notification troubleshooting, consult
[notification examples](src/skills/references/notifications-example.md) as needed.

## Publishing

Before a release, use the repository preflight and keep the skill self-contained.
Do not include internal incident notes or private transcripts in the public bundle.
For the publishing procedure, consult [skill hub publishing](src/skills/references/skill-hub-publishing.md).
Publishing still requires authorization for the target account and repository.
