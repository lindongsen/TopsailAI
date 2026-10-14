"""Nested instruction inspection ownership regressions. Author: DawsonLin."""

from contextvars import Context
from types import SimpleNamespace

import pytest

from topsailai.workspace.plugin_instruction.base import cache
from topsailai.workspace.plugin_instruction.agent import get_messages
from topsailai.workspace.agent.agent_shell_base import AgentChat


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch):
    """Keep the legacy fallback isolated without mutating shared platform state."""
    monkeypatch.setattr(cache, "g_ai_agent", None)
    token = cache._active_ai_agent.set(None)
    try:
        yield
    finally:
        cache._active_ai_agent.reset(token)


class Chat:
    """Exercise the same execution decorator used by AgentChat._run."""

    def __init__(self, name):
        """Register the standalone fallback as the real constructor does."""
        self.ai_agent = SimpleNamespace(messages=[{"role": "assistant", "content": name}])
        cache.set_ai_agent(self.ai_agent)

    @cache.bind_instruction_agent
    def execute(self, callback):
        """Execute one turn under this chat's instruction owner."""
        assert cache.get_ai_agent() is self.ai_agent
        return callback()


def test_standalone_member_inspection():
    """A standalone member remains inspectable before and after execution."""
    member = Chat("standalone-member")
    assert "standalone-member" in get_messages()
    assert member.execute(get_messages) == get_messages()
    cache.set_ai_agent(None)
    assert cache.get_ai_agent() is member.ai_agent


def test_nested_construction_execution_and_return():
    """Construction cannot steal the parent; nested execution restores it."""
    manager = Chat("manager")

    def delegate():
        """Inspect child and grandchild only during their own execution."""
        member = Chat("member")
        assert cache.get_ai_agent() is manager.ai_agent
        assert "manager" in get_messages()

        def child():
            """Verify deeper token restoration and the child's report."""
            grandchild = Chat("grandchild")
            assert cache.get_ai_agent() is member.ai_agent
            assert "grandchild" in grandchild.execute(get_messages)
            assert cache.get_ai_agent() is member.ai_agent
            return get_messages()

        assert "member" in member.execute(child)
        assert cache.get_ai_agent() is manager.ai_agent
        return "done"

    assert manager.execute(delegate) == "done"
    assert cache.get_ai_agent() is manager.ai_agent


@pytest.mark.parametrize("failure", [ValueError("nested failure"), KeyboardInterrupt(), SystemExit(2)])
def test_nested_failure_restores_parent(failure):
    """Ordinary errors and host interruptions restore exact owner identity."""
    manager = Chat("manager")

    def outer():
        """Catch a child failure and inspect the restored manager."""
        member = Chat("member")

        def fail():
            """Raise the original failure object through the binding."""
            raise failure

        with pytest.raises(type(failure)) as caught:
            member.execute(fail)
        assert caught.value is failure
        assert cache.get_ai_agent() is manager.ai_agent

    manager.execute(outer)
    assert cache.get_ai_agent() is manager.ai_agent


def test_outer_failure_restores_fallback():
    """An outer execution failure leaves the original standalone fallback."""
    fallback = Chat("fallback")
    active = SimpleNamespace(ai_agent=SimpleNamespace(messages=[]))

    @cache.bind_instruction_agent
    def fail(self):
        """Fail after observing the executing owner."""
        assert cache.get_ai_agent() is self.ai_agent
        raise RuntimeError("outer failed")

    with pytest.raises(RuntimeError, match="outer failed"):
        fail(active)
    assert cache.get_ai_agent() is fallback.ai_agent


def test_independent_context_does_not_inherit_active_owner():
    """A fresh context has no execution owner from another conversation."""
    manager = Chat("manager")
    member = SimpleNamespace(ai_agent=SimpleNamespace(messages=[]))

    @cache.bind_instruction_agent
    def inspect(self):
        """Observe context-local execution without changing the fallback."""
        assert cache.get_ai_agent() is self.ai_agent
        assert Context().run(cache.get_ai_agent) is manager.ai_agent

    inspect(member)
    assert cache.get_ai_agent() is manager.ai_agent


def test_agent_chat_direct_run_is_bound():
    """Bind the actual _run entry, including direct subagent calls."""
    chat = object.__new__(AgentChat)
    chat.ai_agent = SimpleNamespace(messages=[])
    fallback = Chat("fallback")
    # The first callback executes inside the real _run before any business I/O.
    def stop(*args, **kwargs):
        """Observe the real method owner and stop before session allocation."""
        assert cache.get_ai_agent() is chat.ai_agent
        raise RuntimeError("owner observed")
    chat.call_hooks_pre_run = stop
    assert hasattr(AgentChat._run, "__wrapped__")
    with pytest.raises(RuntimeError, match="owner observed"):
        chat._run()
    assert cache.get_ai_agent() is fallback.ai_agent
