"""Workflow engine: Durable Functions orchestrator + activities (M1 step 2a).

Walking skeleton. Proves end-to-end that a Durable orchestration
registered via :class:`df.Blueprint` coexists with
``create_function_app()`` with no ``host.json`` changes, and that an
LLM-authored plan runs as a sequence of activity invocations.

What is intentionally *not* here yet: fan-out (`context.task_all`),
durable timers (`wait` tasks), cooperative cancel, result templating,
retries, workflow-safe tool registry populated from agent code, the
completion-delivery activity, and the pending-notifications table.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

import azure.durable_functions as df
import azure.functions as func

from .schema import ECHO_TOOL_NAME


ORCHESTRATOR_NAME = "agents_workflow_orchestrator"
_ACTIVITY_NAME = "agents_workflow_run_tool"

WORKFLOW_SAFE_ECHO_TOOL = ECHO_TOOL_NAME

log = logging.getLogger(__name__)


def _run_echo(args: Dict[str, Any]) -> Dict[str, Any]:
    """Trivial workflow-safe tool used to prove activity dispatch."""
    return {"echoed": args}


_DISPATCH: Dict[str, Any] = {ECHO_TOOL_NAME: _run_echo}


def register_workflows(app: func.FunctionApp) -> None:
    """Register the workflow orchestrator + activities on ``app``.

    Expected to be invoked exactly once during app construction.
    Registering twice would double-register Durable bindings and fail
    at worker index time.
    """
    bp = df.Blueprint()

    @bp.activity_trigger(input_name="task")
    def agents_workflow_run_tool(task: Dict[str, Any]) -> Dict[str, Any]:
        task_id = task["id"]
        tool_name = task["tool"]
        args = task.get("args") or {}
        handler = _DISPATCH.get(tool_name)
        if handler is None:
            raise ValueError(
                f"task {task_id!r}: tool {tool_name!r} is not registered "
                "in the workflow-safe dispatch table"
            )
        log.info("workflow activity running: id=%s tool=%s", task_id, tool_name)
        result = handler(args)
        # Determinism contract: activity results must round-trip through JSON.
        json.dumps(result)
        return {"id": task_id, "result": result}

    @bp.orchestration_trigger(context_name="context")
    def agents_workflow_orchestrator(context: df.DurableOrchestrationContext):
        """Execute a linear chain of tool tasks.

        Input: ``{"tasks": [{"id", "tool", "args"}, ...]}``.
        Return: ``{"results": {task_id: tool_result, ...}}``.
        """
        payload: Dict[str, Any] = context.get_input() or {}
        tasks: List[Dict[str, Any]] = list(payload.get("tasks") or [])
        results: Dict[str, Any] = {}

        for task in tasks:
            activity_result = yield context.call_activity(_ACTIVITY_NAME, task)
            results[activity_result["id"]] = activity_result["result"]
            context.set_custom_status(
                f"{len(results)}/{len(tasks)} tasks done"
            )

        return {"results": results}

    app.register_blueprint(bp)


__all__ = [
    "ORCHESTRATOR_NAME",
    "WORKFLOW_SAFE_ECHO_TOOL",
    "register_workflows",
]
