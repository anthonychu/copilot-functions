"""System-prompt addendum + integration entry point for the workflows feature.

Behavioral guidance for the workflow tools is owned by the engine, not
by the agent markdown (see ``docs/workflows.md`` / "DX split"). When an
agent enables workflows in its frontmatter, the framework appends a
short addendum below to the agent's system prompt — covering both
*when* to reach for a workflow and *which* tools the workflow can call —
so every workflow-enabled agent gets the same heuristics without the
author having to copy-paste prose into every agent file.

``build_workflow_integration`` is the one call the app factory makes
to turn on workflows for the main agent: it registers the Durable
engine on the app, computes the effective tool allowlist for this app
from the optional ``workflows.allowed_tools`` frontmatter list, stashes
it on the workflows registry for ``start_workflow`` to read, and
returns the tool list + addendum the chat handlers should thread
through to the agent loop.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import azure.functions as func

from . import registry
from .engine import register_workflows
from .tools import build_workflow_tools

log = logging.getLogger(__name__)


# Kept short on purpose — the individual tool descriptions carry the
# per-tool specifics. This is only about when the LLM should reach for
# a workflow instead of driving the work from chat directly. The
# "Available workflow tools" section is appended dynamically per-app.
_BASE_ADDENDUM = (
    "\n\n"
    "## Long-running work: workflows\n\n"
    "You have access to workflow tools (`start_workflow`, `get_workflow_status`, "
    "`list_workflows`, `cancel_workflow`, `terminate_workflow`).\n\n"
    "Prefer starting a workflow when the user's request involves work that:\n"
    "- would take longer than a single chat turn, or\n"
    "- has steps that can run in parallel and you want them to, or\n"
    "- needs to survive a conversation pause / reconnect.\n\n"
    "`start_workflow` is fire-and-forget. It returns a `workflow_id` immediately "
    "and the orchestration runs in the background. After it returns, briefly "
    "tell the user that work is in flight (include the `workflow_id`) and end "
    "your turn — **do not call `get_workflow_status` to wait for completion or "
    "to surface the final result.** The chat client renders live per-task "
    "status and the final output to the user outside of this conversation "
    "thread; workflow output is not pushed back to you as a tool result.\n\n"
    "Only call `get_workflow_status` (or `list_workflows`) when the user "
    "explicitly asks about a previously-started workflow — for example "
    "*\"what did the incident workflow find?\"* or *\"is workflow X still "
    "running?\"*. Polling on your own initiative wastes turns and tokens "
    "and adds nothing the user can't already see. If a user-prompted "
    "status check returns a non-terminal state (Running, Pending), tell "
    "the user the workflow is still in flight and end the turn — do not "
    "call `get_workflow_status` again in the same turn waiting for it to "
    "finish.\n\n"
    "If the user changes their mind, prefer `cancel_workflow` (cooperative; "
    "preserves partial results) over `terminate_workflow` (abrupt). For short, "
    "latency-sensitive work that fits comfortably in a single turn, keep using "
    "direct tool calls — workflows add overhead."
)

# Backwards-compat: tests import this constant. With per-app tool
# listings the *complete* addendum is now built by
# ``_build_addendum``; this constant is the static prefix only.
WORKFLOW_SYSTEM_ADDENDUM = _BASE_ADDENDUM


def _workflows_enabled(metadata: Dict[str, Any]) -> bool:
    block = metadata.get("workflows")
    if not isinstance(block, dict):
        return False
    return bool(block.get("enabled", False))


def _read_allowed_tools(metadata: Dict[str, Any]) -> Optional[List[str]]:
    """Extract and shape-check ``workflows.allowed_tools`` from frontmatter.

    Returns ``None`` when the field is omitted (caller falls back to
    ``registry.public_tool_names()``). Raises ``RuntimeError`` if the
    field is present but malformed — fail fast at app start with a
    clear error rather than silently degrading to "everything allowed".
    """
    block = metadata.get("workflows") or {}
    if "allowed_tools" not in block:
        return None
    raw = block["allowed_tools"]
    if not isinstance(raw, list) or not all(isinstance(x, str) and x for x in raw):
        raise RuntimeError(
            "workflows.allowed_tools must be a list of non-empty strings; "
            f"got {raw!r}"
        )
    return list(raw)


def _compute_effective_allowlist(
    requested: Optional[List[str]],
) -> frozenset:
    """Validate the requested allowlist against the registry.

    With no frontmatter override, the effective set is every *public*
    registered tool — internal tools like ``__echo`` stay out of the
    agent's reach by default. With an override, every name must be a
    registered tool (public or not — explicit opt-in) and must not
    collide with a reserved workflow-management tool.
    """
    if requested is None:
        return registry.public_tool_names()
    if not requested:
        # Explicit empty list: agent has workflows.enabled but is
        # allowed to call zero workflow tools. Allowed (the agent could
        # still author wait-only plans) but worth a warning since it's
        # almost always a typo.
        log.warning("workflows.allowed_tools is an empty list — no tool "
                    "tasks will validate.")
        return frozenset()
    reserved = [n for n in requested if n in registry.RESERVED_TOOL_NAMES]
    if reserved:
        raise RuntimeError(
            "workflows.allowed_tools cannot include workflow-management "
            f"tools: {sorted(reserved)}"
        )
    unknown = [n for n in requested if registry.get_entry(n) is None]
    if unknown:
        raise RuntimeError(
            "workflows.allowed_tools contains unknown tool name(s): "
            f"{sorted(unknown)}. Registered tools: "
            f"{sorted(registry.all_registered_names())}"
        )
    return frozenset(requested)


def _build_addendum(allowed_tools: frozenset) -> str:
    """Return the per-app system-prompt addendum.

    Includes the static "when to use workflows" prose plus a dynamic
    "Available workflow tools" section listing each allowed tool's
    name and engine-owned description. This is the single place the
    LLM learns which tool names are valid as workflow node targets.

    Computed once at app start and threaded through ``extra_tools`` /
    ``system_addendum``; M1 does not support runtime allowlist changes.
    The per-agent registry refactor in M3 will rebuild this per agent
    rather than per-app.
    """
    if not allowed_tools:
        tool_section = (
            "\n\n### Available workflow tools\n\n"
            "_No tool tasks are currently allowed for this agent — "
            "workflows can only schedule `wait` tasks._"
        )
    else:
        lines = ["\n\n### Available workflow tools\n"]
        for name in sorted(allowed_tools):
            entry = registry.get_entry(name)
            description = entry.description if entry is not None else ""
            lines.append(f"- `{name}` — {description}")
        tool_section = "\n".join(lines)
    return _BASE_ADDENDUM + tool_section


def build_workflow_integration(
    app: func.FunctionApp, metadata: Dict[str, Any]
) -> Tuple[List[Any], Optional[str]]:
    """Enable workflows for the app if the main agent opted in.

    Returns ``(workflow_tools, system_addendum)``. Both are empty /
    ``None`` when the agent hasn't set ``workflows.enabled: true`` — the
    caller can unconditionally extend its tool list and concat the
    addendum without branching.
    """
    if not _workflows_enabled(metadata):
        # Disabled path is a no-op: do NOT call register_workflows or
        # registry.set_app_config. A previously-configured allowlist (if
        # any) is intentionally left untouched so this function is safe
        # to call multiple times in test scenarios that toggle metadata.
        return [], None

    register_workflows(app)
    requested = _read_allowed_tools(metadata)
    effective = _compute_effective_allowlist(requested)
    registry.set_app_config(effective)
    log.info(
        "workflows enabled for main agent: %d tool(s) allowed (%s)",
        len(effective),
        ", ".join(sorted(effective)) or "<none>",
    )
    return build_workflow_tools(), _build_addendum(effective)


__all__ = [
    "WORKFLOW_SYSTEM_ADDENDUM",
    "build_workflow_integration",
]
