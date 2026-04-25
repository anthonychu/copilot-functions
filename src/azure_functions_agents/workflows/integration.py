"""System-prompt addendum + integration entry point for the workflows feature.

Behavioral guidance for the workflow tools is owned by the engine, not
by the agent markdown (see ``docs/workflows.md`` / "DX split"). When an
agent enables workflows in its frontmatter, the framework appends the
short addendum below to the agent's system prompt so every workflow-
enabled agent gets the same "when to prefer workflows" heuristics
without the author having to copy-paste prose into every agent file.

``build_workflow_integration`` is the one call the app factory makes
to turn on workflows for the main agent: it registers the Durable
engine on the app and returns the tool list + addendum the chat
handlers should thread through to the agent loop. Chat handlers are
responsible for binding a Durable client (``durable_client_input``)
and seeding the per-request ContextVar — see
:mod:`.context`.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import azure.functions as func

from .engine import register_workflows
from .tools import build_workflow_tools

log = logging.getLogger(__name__)


# Kept short on purpose — the individual tool descriptions carry the
# per-tool specifics. This is only about when the LLM should reach for
# a workflow instead of driving the work from chat directly.
WORKFLOW_SYSTEM_ADDENDUM = (
    "\n\n"
    "## Long-running work: workflows\n\n"
    "You have access to workflow tools (`start_workflow`, `get_workflow_status`). "
    "Prefer starting a workflow when the user's request involves work that:\n"
    "- would take longer than a single chat turn, or\n"
    "- has steps that can run in parallel and you want them to, or\n"
    "- needs to survive a conversation pause / reconnect.\n\n"
    "Workflows run in the background. After starting one, return the workflow ID "
    "to the user so they know work is in flight, then call `get_workflow_status` "
    "to check progress — do not rely on results being pushed to the conversation "
    "automatically at this time. For short, latency-sensitive work that fits "
    "comfortably in a single turn, keep using direct tool calls — workflows add "
    "overhead."
)


def _workflows_enabled(metadata: Dict[str, Any]) -> bool:
    block = metadata.get("workflows")
    if not isinstance(block, dict):
        return False
    return bool(block.get("enabled", False))


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
        return [], None

    register_workflows(app)
    log.info("workflows enabled for main agent")
    return build_workflow_tools(), WORKFLOW_SYSTEM_ADDENDUM


__all__ = [
    "WORKFLOW_SYSTEM_ADDENDUM",
    "build_workflow_integration",
]
