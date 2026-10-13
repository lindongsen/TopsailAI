"""Tests for startup-state wiring in the AgentChat factory."""

import unittest
from unittest.mock import MagicMock, patch

from topsailai.context.agent_startup import AgentStartupState


class TestAgentChatStartupStateWiring(unittest.TestCase):
    """Verify the real factory and implementation share one state object."""

    def _run_real_factory(self, session_id, message):
        """Run the public factory with infrastructure isolated at its boundaries."""
        from topsailai.workspace import agent_shell

        captured = {}
        fake_agent = MagicMock()
        fake_agent.runtime.llm_model.max_tokens = 4096
        fake_agent.runtime.llm_model.temperature = 0.3
        fake_chat = MagicMock(first_message=message)
        fake_context = MagicMock(messages=[])

        def capture_session(*args, **kwargs):
            captured["session_state"] = kwargs["agent_startup_state"]
            return True

        with patch.object(agent_shell.ctx_manager, "exists_session", return_value=False), \
                patch.object(agent_shell.ctx_manager, "create_session", side_effect=capture_session), \
                patch.object(agent_shell, "get_ai_agent", return_value=fake_agent), \
                patch.object(agent_shell, "record_project_history"), \
                patch.object(agent_shell, "create_session_meta"), \
                patch.object(agent_shell, "cleanup_session_meta_files"), \
                patch.object(agent_shell, "HookInstruction"), \
                patch.object(agent_shell, "ContextRuntimeData", return_value=fake_context), \
                patch.object(agent_shell, "ContextRuntimeAIAgent"), \
                patch.object(agent_shell, "ContextRuntimeInstructions"), \
                patch.object(agent_shell, "AgentChat", return_value=fake_chat), \
                patch.object(agent_shell, "_cleanup_stale_interrupt_flag"):
            result = agent_shell.get_agent_chat(
                session_id=session_id,
                message=message,
                need_input_message=False,
                need_project_workspace_lock=False,
            )

        captured["agent_state"] = fake_agent.startup_state
        self.assertIs(result, fake_chat)
        self.assertIs(captured["session_state"], captured["agent_state"])
        return captured["session_state"]

    def test_factory_passes_same_fresh_state_to_session_and_agent(self):
        """The real public factory shares one state with session naming and Agent."""
        state = self._run_real_factory("same-session", "first")
        self.assertIsInstance(state, AgentStartupState)
        self.assertFalse(state.started)

    def test_repeated_same_session_factory_calls_use_different_states(self):
        """Session IDs do not make startup state global or shared."""
        first = self._run_real_factory("same-session", "first")
        second = self._run_real_factory("same-session", "second")
        self.assertIsNot(first, second)

    def test_factory_cancels_state_when_construction_fails(self):
        """Construction failure settles the state so naming cannot wait forever."""
        from topsailai.workspace import agent_shell

        captured = []

        def fail(**kwargs):
            captured.append(kwargs["agent_startup_state"])
            raise RuntimeError("construction failed")

        with patch.object(agent_shell, "_get_agent_chat_impl", side_effect=fail):
            with self.assertRaisesRegex(RuntimeError, "construction failed"):
                agent_shell.get_agent_chat(
                    session_id="failed-session", message="task", need_project_workspace_lock=False
                )

        self.assertEqual(len(captured), 1)
        self.assertFalse(captured[0].started)
        self.assertFalse(captured[0].wait(0))


if __name__ == "__main__":
    unittest.main()
