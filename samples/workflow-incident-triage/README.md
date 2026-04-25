# Workflow Incident Triage (work in progress)

Sample app for the upcoming **dynamic workflows** feature. The agent persona is
scaffolded but `workflows.enabled` is intentionally commented out in
`main.agent.md` until the agent-tool wiring lands in M1 step 2b. This
directory currently hosts the **2a walking-skeleton engine**, exercised
through a pair of throwaway HTTP endpoints that will be removed when the
agent-facing tools take over.

See the [dynamic workflows reference](../../docs/workflows.md) for the full
feature design.

Tracked by [issue #2](https://github.com/anthonychu/azure-functions-agents/issues/2).

| Trigger | Custom Tools | Connectors | MCP Servers | Skills | Sandbox | Chat UI |
|---|---|---|---|---|---|---|
| HTTP | | | | | | ✅ |

## Status

- [x] M1 step 0 — Durable extension reachability smoke test *(removed in 2a)*
- [x] M1 step 1 — `docs/workflows.md` + sample scaffold
- [x] M1 step 2a — walking-skeleton engine (linear chain via throwaway HTTP harness)
- [x] M1 step 2b — agent tools + system-prompt addendum *(this file)*
- [ ] M1 step 2c — completion delivery + live-progress chat UI
- [ ] M1 step 3+ — primitives (fan-out, timer, cancel, allowlist)

## Run locally

Follow the [shared local development guide](../README.md#run-locally) for
Python env setup, `local.settings.json`, Azurite, and `func start`. This sample
has no extra prerequisites beyond `GITHUB_TOKEN` (used by the placeholder
agent) and Azurite (used by Durable Functions' default Azure Storage backend).

> [!IMPORTANT]
> Activate the venv in the same shell as `func start`. Core Tools uses the
> Python worker from whatever interpreter is on `PATH`; if the venv isn't
> active, the worker will miss `azure-functions-durable` and fail indexing.

### Driving workflows from chat (step 2b)

`workflows.enabled: true` is set in `main.agent.md`, so the framework
injects two tools into the agent's tool schema and appends a short
engine-owned addendum to its system prompt:

- `start_workflow({tasks: [...]})` — validates and launches a workflow,
  returns `{workflow_id}` immediately.
- `get_workflow_status({workflow_id})` — returns the status envelope.

Open the chat UI at <http://localhost:7071/> and ask the agent something
that justifies background work. At this milestone only the `__echo`
tool is workflow-safe (real workflow-safe tools land when step 3
introduces the allowlist), so a useful demo prompt is:

> Start a two-step workflow that uses the `__echo` tool to echo `{"msg": "hello"}`
> and then `{"msg": "world"}`. Return the workflow id, then wait a moment and
> check its status.

You should see tool-call bubbles for `start_workflow` and, on a
subsequent turn, `get_workflow_status` returning a `Completed` envelope
with both echoed results. Live-progress polling lands in step 2c.

## What this sample will demonstrate (when complete)

Open the chat UI (`http://localhost:7071/`) and say something like:

> *"We're seeing latency spikes in the ordering service. Pull recent logs,
> metrics, and the deploy history, give it 30 seconds for in-flight data to
> settle, then summarize what you find and tell me when you're done."*

The agent will:

1. Produce a fan-out DAG (parallel log/metric/deploy fetches → 30s durable
   timer → summarize).
2. Call `start_workflow` and return a workflow ID to the chat.
3. Tell you the result will appear automatically when the workflow finishes.
4. The chat UI's background poll renders a live per-node progress view and
   replaces it with the final report when the workflow completes — typically
   under a minute.

Same demo works through the MCP server and through the existing HTTP API.
