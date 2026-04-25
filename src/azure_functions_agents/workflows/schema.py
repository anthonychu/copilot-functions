"""Workflow plan schema (M1 step 2a — linear-only walking skeleton).

Scope at 2a: validate the smallest plan shape that still lets the engine
prove end-to-end execution. Only `tool` tasks are accepted, `depends_on`
must describe a linear chain. Fan-out, `wait` tasks, templating, retries,
and timeouts land in later steps.
"""

from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, Field, ValidationError


class PlanValidationError(ValueError):
    """Raised when a plan fails structural or semantic validation.

    Message is intended to be surfaced to the LLM caller so it can
    self-correct and resubmit.
    """


class WorkflowTask(BaseModel):
    id: str = Field(..., min_length=1, max_length=64)
    type: str = Field(default="tool")
    tool: str = Field(..., min_length=1)
    args: Dict[str, Any] = Field(default_factory=dict)
    depends_on: List[str] = Field(default_factory=list)


class WorkflowPlan(BaseModel):
    version: int = Field(default=1)
    tasks: List[WorkflowTask] = Field(..., min_length=1)


ECHO_TOOL_NAME: str = "__echo"
ALLOWED_TOOL_NAMES: frozenset[str] = frozenset({ECHO_TOOL_NAME})


def validate_plan(raw: Dict[str, Any]) -> WorkflowPlan:
    """Validate and normalize a plan dict.

    Raises :class:`PlanValidationError` with a caller-friendly message on
    any structural or semantic problem.
    """
    try:
        plan = WorkflowPlan.model_validate(raw)
    except ValidationError as exc:
        raise PlanValidationError(f"plan does not match schema: {exc}") from exc

    seen: set[str] = set()
    for task in plan.tasks:
        if task.id in seen:
            raise PlanValidationError(f"duplicate task id: {task.id!r}")
        seen.add(task.id)

        if task.type != "tool":
            raise PlanValidationError(
                f"task {task.id!r}: type {task.type!r} is not supported at this "
                "milestone (only 'tool' tasks are accepted in the 2a walking skeleton)"
            )

        if task.tool not in ALLOWED_TOOL_NAMES:
            raise PlanValidationError(
                f"task {task.id!r}: tool {task.tool!r} is not workflow-safe. "
                f"Allowed tools at this milestone: {sorted(ALLOWED_TOOL_NAMES)}"
            )

    # Linear-chain check. Arbitrary DAGs land with fan-out support later.
    for idx, task in enumerate(plan.tasks):
        if idx == 0:
            if task.depends_on:
                raise PlanValidationError(
                    f"task {task.id!r}: first task cannot have depends_on "
                    "(linear-chain only at this milestone)"
                )
            continue
        expected = [plan.tasks[idx - 1].id]
        # Require non-first tasks to declare depends_on explicitly so the
        # plan's intent is unambiguous. An empty depends_on would parse today
        # as "sequential" (the orchestrator runs tasks in array order) but
        # would become "parallel" once fan-out support lands — we reject it
        # now to avoid a silent semantic migration later.
        if task.depends_on != expected:
            raise PlanValidationError(
                f"task {task.id!r}: depends_on must be {expected!r} "
                "(only linear chains are supported at this milestone; "
                "each non-first task must explicitly name its predecessor)"
            )

    return plan


def plan_to_activity_inputs(plan: WorkflowPlan) -> List[Dict[str, Any]]:
    """Flatten a validated plan into the JSON list the orchestrator iterates."""
    return [
        {"id": t.id, "tool": t.tool, "args": dict(t.args)}
        for t in plan.tasks
    ]


__all__ = [
    "ALLOWED_TOOL_NAMES",
    "ECHO_TOOL_NAME",
    "PlanValidationError",
    "WorkflowPlan",
    "WorkflowTask",
    "plan_to_activity_inputs",
    "validate_plan",
]
