"""Unit tests for the workflow tool registry and integration glue (M1 step 3c).

Exercises:

- ``register_workflow_tool`` invariants: collision, reserved names,
  async rejection, public/private flag.
- ``validate_plan(allowed_tools=...)`` honoring the explicit allowlist
  and isolating it from the module-level fallback used by older tests.
- ``build_workflow_integration`` reading ``workflows.allowed_tools``
  from frontmatter, rejecting unknown / reserved entries, defaulting
  to the public-tools set, and emitting an addendum that lists the
  effective allowlist.
"""

from __future__ import annotations

import pytest

from azure_functions_agents.workflows import integration, registry, schema, tools


@pytest.fixture(autouse=True)
def _reset_registry():
    """Restore the registry around every test.

    The engine's ``__echo`` registration runs at module import; we
    cache + restore the entries explicitly so other tests in the suite
    see the same starting state regardless of order.
    """
    saved_entries = dict(registry._REGISTRY)
    saved_allow = registry.get_app_config()
    yield
    registry._REGISTRY.clear()
    registry._REGISTRY.update(saved_entries)
    registry.set_app_config(saved_allow if saved_allow is not None else frozenset())
    # set_app_config requires a frozenset; restore None when there was none
    if saved_allow is None:
        registry._APP_ALLOWLIST = None


def _noop(args):
    return {"args": dict(args)}


# ---- registry ---------------------------------------------------------------


def test_register_workflow_tool_rejects_collision():
    registry.register_workflow_tool("alpha", "alpha tool", _noop)
    with pytest.raises(ValueError, match="already registered"):
        registry.register_workflow_tool("alpha", "alpha tool again", _noop)


def test_register_workflow_tool_rejects_reserved_name():
    for reserved in registry.RESERVED_TOOL_NAMES:
        with pytest.raises(ValueError, match="reserved"):
            registry.register_workflow_tool(reserved, "no", _noop)


def test_reserved_names_match_management_tools():
    """Parity guard: RESERVED_TOOL_NAMES must enumerate every tool that
    ``build_workflow_tools`` actually injects, otherwise a future
    addition could shadow a node-target name without anyone noticing.
    """
    actual = {tool.name for tool in tools.build_workflow_tools()}
    assert actual == set(registry.RESERVED_TOOL_NAMES)


def test_register_workflow_tool_rejects_async_handler():
    async def async_handler(args):
        return {}

    with pytest.raises(ValueError, match="async handlers are not supported"):
        registry.register_workflow_tool("asynctool", "no", async_handler)


def test_register_workflow_tool_rejects_non_callable():
    with pytest.raises(ValueError, match="must be a callable"):
        registry.register_workflow_tool("badtool", "no", "not a callable")  # type: ignore[arg-type]


def test_register_workflow_tool_rejects_blank_name():
    with pytest.raises(ValueError, match="non-empty string"):
        registry.register_workflow_tool("", "no", _noop)


def test_public_flag_excludes_tool_from_default_set():
    registry.register_workflow_tool("private_one", "no", _noop, public=False)
    registry.register_workflow_tool("public_one", "yes", _noop, public=True)
    public = registry.public_tool_names()
    assert "public_one" in public
    assert "private_one" not in public
    # __echo (registered at engine import) is also private.
    assert "__echo" not in public


# ---- validate_plan(allowed_tools=...) --------------------------------------


def _plan_one_tool(tool_name):
    return {
        "tasks": [
            {"id": "t1", "type": "tool", "tool": tool_name, "args": {}, "depends_on": []}
        ]
    }


def test_validate_plan_explicit_allowlist_accepts():
    registry.register_workflow_tool("evidence", "x", _noop)
    plan = schema.validate_plan(
        _plan_one_tool("evidence"), allowed_tools={"evidence"}
    )
    assert plan.tasks[0].tool == "evidence"


def test_validate_plan_explicit_allowlist_rejects_disallowed():
    registry.register_workflow_tool("evidence", "x", _noop)
    with pytest.raises(schema.PlanValidationError, match="not workflow-safe"):
        schema.validate_plan(
            _plan_one_tool("evidence"), allowed_tools={"something_else"}
        )


def test_validate_plan_requires_explicit_allowlist():
    # The fallback is gone — callers must pass allowed_tools.
    with pytest.raises(TypeError):
        schema.validate_plan(_plan_one_tool("__echo"))  # type: ignore[call-arg]


def test_validate_plan_with_empty_allowlist_rejects_any_tool():
    with pytest.raises(schema.PlanValidationError, match="not workflow-safe"):
        schema.validate_plan(_plan_one_tool("__echo"), allowed_tools=set())


# ---- build_workflow_integration --------------------------------------------


class _FakeApp:
    """Minimal stand-in so we can call build_workflow_integration without
    spinning up a real azure.functions FunctionApp.

    register_workflows only calls .register_blueprint on us.
    """

    def __init__(self):
        self.blueprints = []

    def register_blueprint(self, bp):
        self.blueprints.append(bp)


def _enable_metadata(allowed=None):
    block = {"enabled": True}
    if allowed is not None:
        block["allowed_tools"] = allowed
    return {"workflows": block}


def test_integration_default_allowlist_is_public_tools_only():
    registry.register_workflow_tool("alpha", "alpha desc", _noop)
    registry.register_workflow_tool("beta", "beta desc", _noop, public=False)
    tools, addendum = integration.build_workflow_integration(
        _FakeApp(), _enable_metadata()
    )
    assert tools  # 5 management tools registered
    assert "alpha" in addendum
    assert "beta" not in addendum
    # __echo is private and must not leak into the default allowlist.
    assert "__echo" not in addendum
    effective = registry.get_app_config()
    assert effective is not None
    assert "alpha" in effective and "beta" not in effective


def test_integration_explicit_allowlist_admits_private_tools():
    registry.register_workflow_tool("alpha", "alpha desc", _noop, public=False)
    _, addendum = integration.build_workflow_integration(
        _FakeApp(), _enable_metadata(allowed=["alpha"])
    )
    assert "alpha" in addendum
    assert registry.get_app_config() == frozenset({"alpha"})


def test_integration_unknown_tool_in_allowlist_fails_at_app_start():
    with pytest.raises(RuntimeError, match="unknown tool name"):
        integration.build_workflow_integration(
            _FakeApp(), _enable_metadata(allowed=["does_not_exist"])
        )


def test_integration_reserved_tool_in_allowlist_fails_at_app_start():
    with pytest.raises(RuntimeError, match="cannot include workflow-management"):
        integration.build_workflow_integration(
            _FakeApp(), _enable_metadata(allowed=["start_workflow"])
        )


def test_integration_malformed_allowlist_fails_at_app_start():
    with pytest.raises(RuntimeError, match="must be a list of non-empty strings"):
        integration.build_workflow_integration(
            _FakeApp(), {"workflows": {"enabled": True, "allowed_tools": "not-a-list"}}
        )


def test_integration_empty_allowlist_yields_empty_effective_set():
    tools, addendum = integration.build_workflow_integration(
        _FakeApp(), _enable_metadata(allowed=[])
    )
    assert tools  # management tools still come back
    assert "No tool tasks are currently allowed" in addendum
    assert registry.get_app_config() == frozenset()


def test_integration_disabled_returns_empty_and_does_not_set_config():
    # Stash a sentinel and ensure the disabled path doesn't clobber it.
    registry.set_app_config(frozenset({"sentinel"}))
    tools, addendum = integration.build_workflow_integration(
        _FakeApp(), {"workflows": {"enabled": False}}
    )
    assert tools == [] and addendum is None
    assert registry.get_app_config() == frozenset({"sentinel"})


def test_addendum_includes_per_tool_descriptions():
    registry.register_workflow_tool(
        "demo_evidence_tool",
        "Sample tool for the addendum-rendering test.",
        _noop,
    )
    _, addendum = integration.build_workflow_integration(
        _FakeApp(), _enable_metadata(allowed=["demo_evidence_tool"])
    )
    assert "## Long-running work: workflows" in addendum
    assert "### Available workflow tools" in addendum
    assert "`demo_evidence_tool`" in addendum
    assert "Sample tool for the addendum-rendering test." in addendum


def test_addendum_enforces_fire_and_forget_no_poll_guidance():
    """Regression guard: the addendum, the start_workflow tool description,
    and the get_workflow_status tool description must all instruct the LLM
    to NOT poll after start_workflow. The chat UI is the result channel.
    A previous version of these prompts told the agent to poll, which kept
    the agent's turn alive and (a) burned tokens and (b) blocked the chat
    input box from re-enabling — surfacing as the demo bug that motivated
    this guard.
    """
    registry.register_workflow_tool(
        "demo_evidence_tool",
        "Sample tool for the no-poll regression test.",
        _noop,
    )
    tools, addendum = integration.build_workflow_integration(
        _FakeApp(), _enable_metadata(allowed=["demo_evidence_tool"])
    )
    # Addendum contract: explicit fire-and-forget framing + explicit
    # negative on get_workflow_status auto-polling.
    assert "fire-and-forget" in addendum
    assert "end your turn" in addendum
    assert "do not call `get_workflow_status` to wait" in addendum
    # Tool descriptions must not encourage polling either, otherwise the
    # tool-call contract overrides the addendum.
    descriptions = {tool.name: tool.description for tool in tools}
    assert "fire-and-forget" in descriptions["start_workflow"]
    assert "do not poll get_workflow_status" in descriptions["start_workflow"]
    assert "only when the user explicitly asks" in descriptions["get_workflow_status"]
    # Negative checks: the prior wording must not creep back in.
    assert "Poll this" not in descriptions["get_workflow_status"]
    assert "call get_workflow_status to check progress" not in descriptions["start_workflow"]
