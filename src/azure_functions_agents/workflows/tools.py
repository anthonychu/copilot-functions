"""Agent-facing workflow tools (M1 step 2c).

Four tools:

- ``start_workflow`` — validate + start a workflow; return ``{"workflow_id"}``.
- ``get_workflow_status`` — return the status envelope for a workflow.
- ``list_workflows`` — list this session's recent workflows.
- ``terminate_workflow`` — hard-stop a workflow; no cooperative cleanup.

All four call the Durable client directly via the per-session registry
populated by the chat handler's ``durable_client_input`` binding.
Ownership is enforced by prefix-matching the Durable instance ID
against ``sha256(session_id)[:12]``; a mismatch returns 404 (same shape
as "not found") to avoid leaking existence of other sessions'
workflows. Cooperative ``cancel_workflow`` lands with the fan-out
orchestrator changes (it needs ``wait_for_external_event`` plumbing on
the orchestrator side).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from copilot import define_tool
from copilot.tools import ToolInvocation
from pydantic import BaseModel, Field

from .context import (
    get_workflow_session,
    new_workflow_instance_id,
    session_owns_workflow,
)
from .engine import ORCHESTRATOR_NAME
from .schema import PlanValidationError, plan_to_activity_inputs, validate_plan

log = logging.getLogger(__name__)


class _TaskSpec(BaseModel):
    id: str = Field(description="Unique identifier for this task within the plan.")
    type: str = Field(
        default="tool",
        description=(
            "Task type. Only 'tool' is supported at this milestone; 'wait' and sub-agent "
            "tasks land in later milestones."
        ),
    )
    tool: str = Field(
        description=(
            "Name of a workflow-safe tool to invoke. The list of allowed tool names is "
            "restricted — an unknown name causes the plan to be rejected."
        )
    )
    args: Dict[str, Any] = Field(
        default_factory=dict, description="JSON-serializable arguments passed to the tool."
    )
    depends_on: List[str] = Field(
        default_factory=list,
        description=(
            "IDs of tasks that must complete before this one. At the current milestone, "
            "plans must be a linear chain (each task depends on at most its immediate "
            "predecessor); fan-out support lands in a later step."
        ),
    )


class StartWorkflowParams(BaseModel):
    tasks: List[_TaskSpec] = Field(
        description=(
            "Ordered list of tasks making up the workflow plan. Linear chains only at "
            "this milestone."
        ),
        min_length=1,
    )


class GetWorkflowStatusParams(BaseModel):
    workflow_id: str = Field(
        description="Workflow ID returned by a prior call to start_workflow."
    )


class ListWorkflowsParams(BaseModel):
    """No parameters — lists recent workflows owned by the calling session."""


class TerminateWorkflowParams(BaseModel):
    workflow_id: str = Field(
        description="Workflow ID returned by a prior call to start_workflow."
    )
    reason: str = Field(
        default="terminated by agent",
        description="Short human-readable reason recorded on the Durable instance.",
    )


def status_envelope(status: Any) -> dict:
    """Normalize a Durable instance status into the tool-facing envelope."""
    if status is None:
        return {"workflow_id": None, "runtime_status": "not_found"}
    runtime_status = getattr(status.runtime_status, "name", str(status.runtime_status))
    return {
        "workflow_id": status.instance_id,
        "runtime_status": runtime_status,
        "custom_status": status.custom_status,
        "output": status.output,
        "created_time": status.created_time.isoformat() if status.created_time else None,
        "last_updated_time": (
            status.last_updated_time.isoformat() if status.last_updated_time else None
        ),
    }


# Backwards-compatible alias for in-module call sites; do not export.
_status_envelope = status_envelope


async def fetch_session_workflows(
    durable_client: Any, session_id: str
) -> List[Dict[str, Any]]:
    """Return status envelopes for all workflows owned by ``session_id``.

    Shared between the ``list_workflows`` tool (LLM-facing) and the
    ``/agent/workflows`` HTTP endpoint (UI polling). See the note in
    ``list_workflows`` about the SDK's missing ``instance_id_prefix``
    filter (FU-7) — until that lands we pull the full instance list
    and filter in memory.
    """
    statuses = await durable_client.get_status_all()
    envelopes: List[Dict[str, Any]] = []
    for status in statuses or []:
        instance_id = getattr(status, "instance_id", None)
        if not instance_id or not session_owns_workflow(session_id, instance_id):
            continue
        envelopes.append(status_envelope(status))
    envelopes.sort(
        key=lambda env: env.get("last_updated_time") or "",
        reverse=True,
    )
    return envelopes


async def fetch_session_workflow_status(
    durable_client: Any, session_id: str, workflow_id: str
) -> Optional[Dict[str, Any]]:
    """Return the status envelope for ``workflow_id`` if owned by
    ``session_id``; otherwise ``None`` (404 semantics).
    """
    if not session_owns_workflow(session_id, workflow_id):
        return None
    status = await durable_client.get_status(workflow_id)
    envelope = status_envelope(status)
    if envelope["runtime_status"] == "not_found":
        return None
    return envelope


def _error(message: str, **extra: Any) -> str:
    return json.dumps({"error": message, **extra})


_NO_CLIENT_MESSAGE = (
    "workflow tools are not available in this request context (the enclosing "
    "chat handler did not register a Durable client for this session)"
)

_NOT_FOUND_ERROR_STATUS = 404


@define_tool(
    description=(
        "Author and launch a long-running workflow. The workflow runs as a durable "
        "background orchestration; this tool returns as soon as the workflow is "
        "scheduled, so the conversation can continue. Use it when the work needs to "
        "survive across chat turns, when you want steps to run in parallel, or when "
        "the total work would exceed a typical tool-call budget. The `tasks` input is "
        "an ordered list; at this milestone tasks must form a linear chain (each task "
        "depends on at most its immediate predecessor). Returns {workflow_id} on "
        "success; call get_workflow_status with that ID to check progress."
    )
)
async def start_workflow(params: StartWorkflowParams, invocation: ToolInvocation) -> str:
    session = get_workflow_session(invocation.session_id)
    if session is None:
        return _error(_NO_CLIENT_MESSAGE)

    try:
        plan = validate_plan(params.model_dump())
    except PlanValidationError as exc:
        return _error(str(exc))

    owner = {
        "session_id": session.session_id,
        "agent_name": session.agent_name,
    }
    instance_id = new_workflow_instance_id(session.session_id)

    try:
        returned_id = await session.durable_client.start_new(
            ORCHESTRATOR_NAME,
            instance_id=instance_id,
            client_input={
                "tasks": plan_to_activity_inputs(plan),
                "owner": owner,
            },
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("start_workflow: client.start_new failed")
        return _error(f"failed to start workflow: {exc}")

    # Durable echoes back the instance ID we supplied; defend against SDK
    # drift by logging a mismatch but trusting our own value.
    if returned_id != instance_id:
        log.warning(
            "start_workflow: Durable returned instance_id=%r but we supplied %r",
            returned_id,
            instance_id,
        )
    log.info("workflow started: id=%s owner=%s", instance_id, owner["session_id"])
    return json.dumps({"workflow_id": instance_id})


@define_tool(
    description=(
        "Return the current status of a previously-started workflow. Poll this to "
        "learn when a workflow has completed and to read its output. The returned "
        "envelope includes runtime_status (one of: Running, Completed, Failed, "
        "Terminated, Canceled, Pending), an optional short custom_status string with "
        "progress, and — once the workflow reaches a terminal state — the output. "
        "Only workflows started by the same agent session are visible."
    )
)
async def get_workflow_status(
    params: GetWorkflowStatusParams, invocation: ToolInvocation
) -> str:
    session = get_workflow_session(invocation.session_id)
    if session is None:
        return _error(_NO_CLIENT_MESSAGE)

    # Ownership check via instance-ID prefix. Any workflow whose ID does
    # not start with this session's hash is treated as nonexistent — same
    # shape as "not found" so existence cannot be probed.
    if not session_owns_workflow(session.session_id, params.workflow_id):
        return _error(
            f"workflow {params.workflow_id!r} not found",
            status=_NOT_FOUND_ERROR_STATUS,
        )

    try:
        status = await session.durable_client.get_status(params.workflow_id)
    except Exception as exc:  # noqa: BLE001
        log.exception("get_workflow_status: client.get_status failed")
        return _error(f"failed to fetch workflow status: {exc}")

    envelope = _status_envelope(status)
    if envelope["runtime_status"] == "not_found":
        return _error(
            f"workflow {params.workflow_id!r} not found",
            status=_NOT_FOUND_ERROR_STATUS,
        )
    return json.dumps(envelope)


@define_tool(
    description=(
        "List workflows started by this agent session. Returns an array of "
        "status envelopes, newest first, in the same shape as "
        "get_workflow_status. Includes active workflows regardless of age "
        "and terminal workflows that have not yet been purged from Durable "
        "history. Use this to find workflow IDs if you have lost track of "
        "them or to check on multiple concurrent workflows."
    )
)
async def list_workflows(
    params: ListWorkflowsParams, invocation: ToolInvocation
) -> str:
    session = get_workflow_session(invocation.session_id)
    if session is None:
        return _error(_NO_CLIENT_MESSAGE)

    try:
        envelopes = await fetch_session_workflows(
            session.durable_client, session.session_id
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("list_workflows: fetch_session_workflows failed")
        return _error(f"failed to list workflows: {exc}")

    return json.dumps({"workflows": envelopes})


@define_tool(
    description=(
        "Hard-stop a running workflow. The Durable instance stops abruptly; no "
        "completion push-back is guaranteed. Prefer this when a workflow is "
        "clearly wrong and must not continue; for clean shutdown of workflows "
        "that could leave partial state, wait for them to finish on their own. "
        "Only workflows started by the same agent session can be terminated."
    )
)
async def terminate_workflow(
    params: TerminateWorkflowParams, invocation: ToolInvocation
) -> str:
    session = get_workflow_session(invocation.session_id)
    if session is None:
        return _error(_NO_CLIENT_MESSAGE)

    if not session_owns_workflow(session.session_id, params.workflow_id):
        return _error(
            f"workflow {params.workflow_id!r} not found",
            status=_NOT_FOUND_ERROR_STATUS,
        )

    try:
        await session.durable_client.terminate(params.workflow_id, params.reason)
    except Exception as exc:  # noqa: BLE001
        log.exception("terminate_workflow: client.terminate failed")
        return _error(f"failed to terminate workflow: {exc}")

    log.info(
        "workflow terminated: id=%s reason=%r", params.workflow_id, params.reason
    )
    return json.dumps({"workflow_id": params.workflow_id, "terminated": True})


def build_workflow_tools() -> list:
    """Return the list of workflow tool objects to inject for an agent."""
    return [start_workflow, get_workflow_status, list_workflows, terminate_workflow]


__all__ = [
    "GetWorkflowStatusParams",
    "ListWorkflowsParams",
    "StartWorkflowParams",
    "TerminateWorkflowParams",
    "build_workflow_tools",
    "fetch_session_workflow_status",
    "fetch_session_workflows",
    "get_workflow_status",
    "list_workflows",
    "start_workflow",
    "status_envelope",
    "terminate_workflow",
]
