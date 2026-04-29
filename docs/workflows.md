# Dynamic workflows (in progress)

> [!NOTE]
> **Status: design complete, implementation in progress.** This feature is
> being built incrementally. Tracking issue:
> [anthonychu/azure-functions-agents#2](https://github.com/anthonychu/azure-functions-agents/issues/2).
> The behavior described below is the target for **M1**; individual
> primitives land one at a time. Run the [workflow-incident-triage
> sample](../samples/workflow-incident-triage/README.md) to see what works
> today.

Dynamic workflows let a markdown agent author and run **distributed,
observable, durable** plans without writing orchestration code. Flip
`workflows.enabled: true` in the agent's frontmatter and the agent gains a
small set of built-in tools that author and launch
[Azure Durable Functions](https://learn.microsoft.com/azure/azure-functions/durable/)
orchestrations of tool calls, sub-agents, and timers.

## Who this is for

Dynamic workflows are a fit when an agent needs to:

- **process large datasets** where only an aggregate or summary should
  reach the chat (e.g., scan 50 endpoints, summarize anomalies);
- **run multi-step plans** (3+ dependent tool calls) where each model
  round-trip would burn tokens and latency;
- **fan out** independent work across many parallel tool calls;
- **wait** on durable timers or external events without holding a worker
  hot;
- **survive** worker restarts or long pauses (minutes to hours);
- **be observed and controlled** from outside the agent loop;
- **coordinate multiple agents** in the same app (M4+).

They are **not** the right tool for:

- work that fits comfortably inside a single chat turn — the
  orchestration overhead would dominate;
- tools that need an immediate user response (the workflow tool returns
  immediately with an ID; the *result* is fetched on a later turn);
- hand-authored orchestration DSLs — plans are LLM-authored only, by
  design, so there is no YAML/markdown workflow template format;
- cross-app coordination (M1 workflows live inside a single Functions
  app).

## Why workflows (token, latency, context)

Dynamic workflows give an agent the same benefits that motivate
[programmatic tool calling][ptc] in other LLM platforms — the LLM authors
a *plan that calls tools* rather than calling them one-by-one through chat
round-trips — and add durability, observability, and cooperative control
on top.

Three concrete wins versus chaining tool calls in conversation:

- **Lower token cost.** Intermediate task results stay inside the
  orchestration. The agent sees only the final completion envelope (or a
  summary task you wired in), not every fan-out result. Anthropic
  [reports][ptc] roughly a 10× reduction on multi-tool workflows; the
  shape of the saving is the same here.
- **Lower latency.** Each direct tool call is a round-trip through the
  model. A 20-step plan is one model turn to author the workflow, not 20.
  The orchestrator drives the fan-out and sequencing in pure
  infrastructure.
- **Context-window discipline.** Hundreds of kilobytes of intermediate
  data — log lines, line items, search hits — never reach the model's
  context. The agent reasons over the *summary*, which is what it would
  have produced anyway after seeing the raw data.

…and three more that PTC's container-based model can't offer:

- **Survives worker restarts and long sleeps.** Workflows that take hours
  or days are first-class — no client connection has to stay open.
- **Operable from outside the agent loop.** `list_workflows`,
  `get_workflow_status`, `cancel_workflow`, and (in M2+) the DTS portal
  give operators a way to see and steer in-flight work without going
  through the chat session.
- **Multi-agent coordination (M4).** Sub-agent tasks run as durable
  sub-orchestrations with isolated sessions, observable end-to-end.

[ptc]: https://platform.claude.com/docs/en/agents-and-tools/tool-use/programmatic-tool-calling

## How it works

1. You enable workflows on an agent with a one-line frontmatter flag.
2. The agent is given five built-in tools (see [Tools](#tools)).
3. When the agent decides the work is workflow-shaped, it calls
   `start_workflow` with a DAG of tasks. The DAG is validated and scheduled
   as a Durable orchestration; the tool returns immediately with a
   `workflow_id`.
4. The orchestration runs each task as a Durable activity (tool calls) or
   a Durable timer (waits), using `task_all` to fan out parallel tasks and
   `depends_on` edges for sequencing.
5. **`start_workflow` is fire-and-forget from the agent's perspective.**
   After receiving the `workflow_id`, the agent reports it to the user
   and ends its turn. The agent does not poll `get_workflow_status` to
   wait for completion; the workflow result is not pushed back into the
   conversation as a tool result.
6. The chat client (the built-in chat UI, or any external poller) polls
   `GET /agent/workflows` on a short interval while the session is
   visible, renders a live per-task progress card alongside the chat
   thread, and updates the card with the final result envelope when the
   workflow terminates. The user sees progress and the final output
   without the agent doing any work.
7. If the user later asks the agent about a previously-started
   workflow ("what did the incident workflow find?"), the agent calls
   `get_workflow_status` on demand and reports back. This is the only
   path by which workflow output ever enters the agent's context window.

> [!NOTE]
> **Intermediate task results never enter the agent's context window.**
> The agent receives only the `workflow_id` from `start_workflow`. Final
> output is delivered to the user by the chat client outside the agent
> loop; the agent only sees that output if a follow-up user question
> causes it to call `get_workflow_status`. Per-node results are
> accessible programmatically via `get_workflow_status` if the agent
> wants them, but the default path is "summary only." This is the same
> context-window discipline that makes [programmatic tool calling][ptc]
> cheap.

The design is intentionally aligned with the
[MCP Tasks SEP-2557 proposal](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2557);
future direct MCP Tasks support will be a thin protocol shim.

## Frontmatter

```yaml
---
name: Incident Triage Assistant
description: ...
workflows:
  enabled: true
  # Optional allowlist of tools a workflow may call. Defaults to every
  # workflow-safe tool the agent can already use. Workflow-management
  # tools (start_workflow, get_workflow_status, list_workflows,
  # cancel_workflow, terminate_workflow) are always excluded.
  allowed_tools:
    - fetch_url
    - summarize
  # Later-milestone knobs (M5):
  # backend: storage | dts
  # task_hub: AgentWorkflows
  # max_nodes: 100
  # allowed_sub_agents: []   # M4, deny-by-default
---
```

When `workflows.enabled: true`, the framework auto-injects the five
workflow tools into the agent's schema **and** appends a short
behavioral addendum to the agent's system prompt explaining when to
prefer `start_workflow` over direct tool calls. The agent author does
not need to document the tools or the heuristics in their markdown — the
agent markdown stays focused on the domain.

> [!IMPORTANT]
> **M1 constraint:** `workflows.enabled: true` is only honored on
> `main.agent.md` (the interactive, session-backed agent). Other agents
> that set the flag get a startup warning and the tools are not injected.
> M3 lifts this constraint.

## Tools

Five tools are added to the agent's schema when `workflows.enabled: true`:

| Tool | Purpose |
| --- | --- |
| `start_workflow(plan)` | Validate a DAG, start an orchestration, return `{workflow_id}` immediately. |
| `get_workflow_status(workflow_id)` | Return the current status envelope (see below). |
| `list_workflows(status?)` | List workflows owned by the current session, optionally filtered by status. |
| `cancel_workflow(workflow_id, reason?)` | Cooperative cancel — raises an external event the orchestrator handles; the completion activity still runs. |
| `terminate_workflow(workflow_id, reason?)` | Hard terminate — stops the instance abruptly; final status is observable but no completion envelope is guaranteed. |

Workflow-management tools are never reachable as workflow-node targets —
a plan that tries to call `start_workflow` from inside a workflow fails
validation.

## DAG schema (v1)

A workflow plan is a list of tasks with `depends_on` edges. Task types:

- **`tool`** — call a `workflow_safe` tool by name with args.
- **`wait`** — durable timer. Accepts `duration` (ISO-8601, e.g. `PT30S`)
  or `until` (absolute ISO-8601 timestamp).

Each task can optionally carry:

- `timeout` — per-task timeout (default 300s, hard cap 900s).
- `retry` — `{max_attempts, backoff_seconds}` → Durable `RetryOptions`.

```json
{
  "tasks": [
    { "id": "fetch_a", "type": "tool", "tool": "fetch_url", "args": {"url": "..."} },
    { "id": "fetch_b", "type": "tool", "tool": "fetch_url", "args": {"url": "..."} },
    { "id": "cool_down", "type": "wait", "duration": "PT30S",
      "depends_on": ["fetch_a", "fetch_b"] },
    { "id": "summarize", "type": "tool", "tool": "summarize",
      "args": {"sources": ["${fetch_a.result}", "${fetch_b.result}"]},
      "depends_on": ["cool_down"] }
  ]
}
```

### Templating

`${node_id.result}` and `${node_id.result.path.to.field}` are resolved
**inside the orchestrator** against JSON-normalized prior outputs.
Unresolved paths are a deterministic validation failure with
`{missing_path, task_id, path}` in the error envelope.

### Caps (M1 defaults)

Enforced during plan validation and at runtime:

| Cap | Default |
|---|---|
| `max_nodes` | 50 |
| `max_parallelism` | 10 |
| `default_tool_timeout` | 300s |
| `hard_tool_timeout` | 900s |
| `max_wait_duration` | 24h |
| `max_active_workflows_per_session` | 3 |

These are code-level defaults in M1; making them configurable from
frontmatter lands in M5.

### Determinism contract

The orchestrator holds these invariants:

- Ready tasks are scheduled in a deterministic order (sorted by task id).
- Time-dependent logic uses `context.current_utc_datetime` only.
- Activity results must be JSON-serializable; non-serializable results
  cause a hard, deterministic failure.
- Templating is evaluated over JSON-normalized prior outputs.

## Status envelope

Returned by `get_workflow_status` and (per-workflow, in an array) by
`GET /agent/workflows`. The same shape is used everywhere a status is
read so external clients (operator dashboards, MCP Tasks bridges) can
consume a single contract:

```json
{
  "workflow_id": "...",
  "agent_name": "incident-triage",
  "runtime_status": "Running|Completed|Failed|Terminated|Canceled|Pending",
  "custom_status": "3/7 tasks done, current=summarize",
  "output": { "...": "..." },
  "created_time": "...",
  "last_updated_time": "..."
}
```

`runtime_status` is the canonical value the chat UI cards and any
external poller render against. `output` is populated only when the
workflow has reached a terminal state and (for cooperative cancel)
includes any partial results gathered before the cancel signal landed.

## Completion delivery

Completion delivery is **poll-based**, by design. There is no push
channel from the orchestrator into the agent's chat thread.

- The chat client (the built-in chat UI under `/`, or any external
  poller) calls `GET /agent/workflows` on a 2–5 second cadence while
  the chat session is visible. It receives an array of status
  envelopes for the calling session's workflows, renders a per-workflow
  progress card next to the chat thread, and updates the card when the
  workflow reaches a terminal state.
- The agent itself never receives the completion envelope as a tool
  result. After `start_workflow` returns the `workflow_id`, the agent's
  job is done; it should report the ID and end the turn. If the user
  later asks the agent about the workflow, the agent calls
  `get_workflow_status` on demand — that on-demand call is the only
  path by which workflow output enters the agent's context window.
- The `GET /agent/workflows` endpoint is scoped to the calling session
  via the `x-ms-session-id` request header and the per-workflow
  ownership scheme described in [Ownership](#ownership).

The data shape maps directly onto MCP Tasks SEP-2557 (`CreateTaskResult`,
`tasks/get`, `tasks/cancel`); future direct MCP Tasks support is a thin
protocol shim.

## Ownership

Every workflow's Durable instance ID is prefixed with
`sha256(session_id)[:12]` at creation. `get_workflow_status`,
`list_workflows`, `cancel_workflow`, and `terminate_workflow` filter
on that prefix; a workflow whose prefix does not match the calling
session's hash is treated as nonexistent (returns 404, never 403, so
existence cannot be probed by guessing IDs across sessions).

## Observability

- **Live-progress chat UI** (M1) — built-in poll loop renders per-node
  state in the chat session.
- **Durable Task Scheduler portal** (M2) — when `workflows.backend: dts`,
  each workflow appears as a queryable instance with per-task state,
  retry history, and parent-child lineage (for sub-agents, M4).
- **`customStatus`** — the orchestration emits a concise summary
  (`"3/7 tasks done, current=summarize"`) for low-cost polling.
- **Audit records** — an append-only record per workflow links
  `{workflow_id, agent_name, session_id, initiating_tool_call_id, plan_hash, created_at, completed_at, terminated_by, termination_reason}`.

## Requirements

- `azure-functions-durable` (installed transitively with
  `azure-functions-agents`).
- An Azure Storage connection string in `AzureWebJobsStorage` (already
  required for non-HTTP triggers; Azurite works locally). DTS becomes an
  option in M2.
- The default extension bundle (`[4.*, 5.0.0)`) already ships the Durable
  Task extension — no `host.json` changes are required.

## What lands when

See [issue #2](https://github.com/anthonychu/azure-functions-agents/issues/2) for
the milestone breakdown. In short:

- **M1** — engine, 5 tools, fan-out + timer + cancel, live-progress chat
  UI. Single-agent (`main.agent.md`) only.
- **M2** — DTS backend as a first-class option; DTS portal becomes the
  default operator experience.
- **M3** — internal per-agent registry refactor (prerequisite for M4).
- **M4** — sub-agent tasks; workflows can invoke other agents in the
  same app with isolated sessions.
- **M5** — hardening pass (configurable caps/allowlists, HMAC-hashed
  owner keys, blob-offloaded large outputs, richer idempotency, error
  taxonomy, storage hygiene).
