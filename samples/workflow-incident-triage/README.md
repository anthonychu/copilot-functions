# Workflow Incident Triage (work in progress)

Sample app for the upcoming **dynamic workflows** feature. The agent
investigates production incidents by fanning out evidence-gathering
tools, optionally waiting for in-flight signal to settle, and
correlating the results into a structured incident report.

See the [dynamic workflows reference](../../docs/workflows.md) for the full
feature design.

Tracked by [issue #2](https://github.com/anthonychu/azure-functions-agents/issues/2).

| Trigger | Custom Tools | Connectors | MCP Servers | Skills | Sandbox | Chat UI |
|---|---|---|---|---|---|---|
| HTTP | ✅ (workflow-safe) | | | | | ✅ |

## Status

- [x] M1 step 0 — Durable extension reachability smoke test *(removed in 2a)*
- [x] M1 step 1 — `docs/workflows.md` + sample scaffold
- [x] M1 step 2a — walking-skeleton engine (linear chain via throwaway HTTP harness)
- [x] M1 step 2b — agent tools + system-prompt addendum
- [x] M1 step 2c — completion delivery + live-progress chat UI
- [x] M1 step 3a/3b — fan-out, templating, durable timers, cooperative cancel
- [x] M1 step 3c — sample evidence tools + `workflows.allowed_tools` *(this file)*
- [ ] M1 step 4 — additional plan-parser tests
- [ ] M1 step 5 — demo dry-run

## Run locally

Follow the [shared local development guide](../README.md#run-locally) for
Python env setup, `local.settings.json`, Azurite, and `func start`. This sample
has no extra prerequisites beyond `GITHUB_TOKEN` (used by the placeholder
agent) and Azurite (used by Durable Functions' default Azure Storage backend).

> [!IMPORTANT]
> Activate the venv in the same shell as `func start`. Core Tools uses the
> Python worker from whatever interpreter is on `PATH`; if the venv isn't
> active, the worker will miss `azure-functions-durable` and fail indexing.

## Workflow-safe tools registered by this sample

`function_app.py` registers four synthetic-but-realistic tools with the
workflows engine before `create_function_app()` runs. The agent's
`main.agent.md` allow-lists exactly these four, so they are the only
tools the LLM may put on a workflow node:

| Tool | Args | Result shape |
|---|---|---|
| `fetch_logs` | `{service, window_minutes?: int = 30}` | `{service, window_minutes, lines: [str], errors, warnings}` |
| `fetch_metrics` | `{service, window_minutes?: int = 30}` | `{service, window_minutes, cpu_p99, memory_p99, latency_p99_ms, saturation}` |
| `fetch_deploys` | `{service, lookback_hours?: int = 24}` | `{service, lookback_hours, deploys: [{id, actor, summary, minutes_ago}]}` |
| `summarize_findings` | `{logs, metrics, deploys, service?}` (consume whole `${node.result}` values) | `{service, likely_cause, confidence: 'low'\|'medium'\|'high', evidence: [str], recommended_action}` |

Outputs are deterministic functions of inputs so the demo narrative is
reproducible across runs and replays. The summary tool deliberately
consumes the whole upstream result via `${node.result}` — there is no
need (and no benefit) to drill into nested paths from the plan.

## Demo prompt

Open the chat UI at <http://localhost:7071/> and paste:

> *"We're seeing latency spikes and intermittent 502s on the `orders-api`
> service for the last 20 minutes. Pull recent logs, metrics, and the deploy
> history in parallel; let in-flight work drain for 30 seconds; then
> summarize what you find."*

The agent should:

1. Author a five-task workflow: three parallel fetches against `orders-api`,
   a `wait` task with `duration: PT30S` that depends on all three, and a
   final `summarize_findings` task that depends on the wait and consumes
   the three fetch results via `${...result}` templates.
2. Call `start_workflow`, return the `workflow_id` to the chat, and let the
   built-in live-progress card take over.
3. Within ~35 seconds, the workflow should reach `Completed` and the card
   should expose the structured summary (likely cause, confidence,
   evidence, recommended action).

If you want to see cooperative cancellation, ask "actually cancel that"
while the workflow is mid-wait — the agent will call `cancel_workflow`,
the orchestration unwinds at the next wave boundary, and the live card
flips to `Canceled` with whatever partial results were already gathered.

## What's still mocked

The four workflow-safe tools synthesize their evidence from a
deterministic hash of the args — there is no real log / metric /
deploy backend behind them yet. That is deliberate: we want the sample
to exercise every M1 workflow primitive end-to-end without dragging in
external service dependencies. A future milestone (or a fork of this
sample) can swap the handlers for real backends without touching the
agent persona, the workflow plan shape, or the engine.
