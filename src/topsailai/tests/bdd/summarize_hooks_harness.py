"""Real provider and managed-observer summary acceptance. Author: DawsonLin."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path

from tests.mock.llm_mock_server import MockServerConfig, create_server
from topsailai.ai_base.llm_pool.openai_client_pool import default_openai_client_pool
from topsailai.hooks import (
    ArtifactClosureAssertion, ArtifactPythonRuntimeAuthority, ConfiguredHookPoint,
    ConfiguredHooks, ConfiguredTrustPolicy, HookSettings,
)
from topsailai.hooks.artifact_identity import python_runtime_fingerprint
from topsailai.hooks.configured_contracts import ConfiguredPreparationRequest
from tests.summary_catalog_support import (
    PHASE_ONE_DECLARATIONS, PHASE_TWO_DECLARATIONS, SUMMARY_CATALOG,
)
import topsailai.hooks as hooks
from topsailai.hooks.point_entry import pending_cleanup
from topsailai.workspace import agent_shell
from tests import legacy_prepared_support


class SummarizeHooksScenario:
    """Own a configured application, its chats, and a loopback provider."""

    def __init__(self, monkeypatch, request, layer, case, transport):
        """Register cleanup before allocating resources or executing a scenario."""
        self.patch = monkeypatch
        self.layer, self.case, self.transport = layer, case, transport
        self.chats, self.events, self.reports = [], [], []
        self.owner = self.server = self.thread = self.root = None
        self.result = self.error = self.primary = None
        self.application_checked = False
        request.addfinalizer(self.close)
        base = Path(__file__).resolve().parents[2] / '.tmp/u7-summarize-hooks-bdd'
        base.mkdir(parents=True, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix='scenario-', dir=base))
        self.sources = self.root / 'sources'
        self.sources.mkdir(mode=0o700)
        self.ledger = self.root / 'observer.jsonl'
        reply = 'U7 concise summary'
        self.server = create_server(MockServerConfig(
            port=0, reply=reply, stream_chunks=(reply,),
            stream_http_error_responses=((400, 'No tool call found for function call output with call_id u7'),)
            if case == 'generation_failure' else None,
        ))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        url = f'http://127.0.0.1:{self.server.server_port}/v1'
        values = {
            'OPENAI_API_BASE': url, 'OPENAI_BASE_URL': url,
            'OPENAI_API_KEY': 'mock-u7', 'OPENAI_MODEL': 'topsailai-mock-u7',
            'LLM_RESPONSE_STREAM': '1' if transport == 'sse' else '0',
            'TOPSAILAI_CONTEXT_SUMMARY_MODE': 'runtime',
            'TOPSAILAI_CONTEXT_SUMMARY_PROCESSOR': 'agent_llm_model',
            'TOPSAILAI_INTERACTIVE_MODE': '0', 'TOPSAILAI_MODEL_SETTINGS': '',
            'TOPSAILAI_USE_TOOL_CALLS': '0', 'TOPSAILAI_USE_TOOL_CALLS_MODEL_PREFIXES': '',
            'TOPSAILAI_CTX_SUMMARY_KEEP_FIRST_TASK_MESSAGE': '0',
            'TOPSAILAI_CTX_SUMMARY_KEEP_SESSION_MESSAGES': '0',
            'TOPSAILAI_CONTEXT_MESSAGES_HEAD_OFFSET_TO_KEEP': '0',
            'TOPSAILAI_CONTEXT_MESSAGES_TAIL_OFFSET_TO_KEEP': '0',
            'TOPSAILAI_MODEL_MAX_CONTEXT_DEFAULT': '0',
            'TOPSAILAI_MODEL_MAX_CONTEXT_MAP': '',
            'TOPSAILAI_AGENT2LLM_SUMMARY_TOKEN_RESERVE': '0',
            'TOPSAILAI_USER2AGENT_SUMMARY_TOKEN_RESERVE': '0',
            'TOPSAILAI_ENABLE_SESSION_TEE_OUT': '0',
            'TOPSAILAI_TERMINAL_TITLE_ENABLED': '0',
            'TOPSAILAI_AUTO_SESSION_NAME_ENABLED': '0',
            'TOPSAILAI_EVENTS_ENABLED': '0', 'TOPSAILAI_LLM_RESPONSE_EVENTS_ENABLED': '0',
            'TOPSAILAI_DISABLED_TOOLS': '*', 'TOPSAILAI_DISABLED_SKILLS': '*',
            'TOPSAILAI_TASK': '', 'TOPSAILAI_USER_MESSAGE': '', 'SESSION_ID': '',
            'TOPSAILAI_INPUT_PIPE_ENABLED': '0',
            'TOPSAILAI_AGENT2LLM_INJECT_MESSAGE_ENABLED': '0',
        }
        for name, value in values.items():
            monkeypatch.setenv(name, value)
        # Factory input and project-history boundaries have no bearing on LLM traffic.
        monkeypatch.setattr(agent_shell, 'get_message', lambda *a, **k: '')
        default_openai_client_pool.close_all()
        task_root = self.root / 'task'
        task_root.mkdir()
        for module_name, module in tuple(sys.modules.items()):
            if module_name.startswith('topsailai.') and hasattr(module, 'FOLDER_WORKSPACE_TASK'):
                monkeypatch.setattr(module, 'FOLDER_WORKSPACE_TASK', str(task_root))
        monkeypatch.setattr(hooks, '_point_configuration', ())
        self.control = False
        self._prepare()

    def _prepare_legacy(self):
        """Verify retained legacy startup dispositions separately from business wiring."""
        executable = Path(sys.executable).resolve(strict=True)
        digest = hashlib.sha256(executable.read_bytes()).hexdigest()
        status = executable.stat()
        fingerprint = python_runtime_fingerprint(
            executable, digest, device=status.st_dev, inode=status.st_ino)
        points, assertions = [], []
        for point in PHASE_ONE_DECLARATIONS:
            folder = self.sources / point.name
            folder.mkdir(mode=0o700)
            source = folder / 'observer.py'
            source.write_text(
                'import json\n'
                'def main(log, point, fail=False):\n'
                '    """Record a safe configured observation from a managed worker."""\n'
                '    with open(log, "a", encoding="utf-8") as stream:\n'
                '        stream.write(json.dumps({"point": point}) + "\\n")\n'
                '    if fail:\n'
                '        raise RuntimeError("observer fixture failure")\n', encoding='utf-8')
            assertions.append(ArtifactClosureAssertion(
                source, 'python_source', 'observer',
                hashlib.sha256(source.read_bytes()).hexdigest(), fingerprint, '0' * 64))
            points.append(ConfiguredHookPoint(
                point.name, point.definition, module_folder=folder,
                module_args=(str(self.ledger), point.name, self.case == 'observer_failure')))
        disabled = frozenset({PHASE_ONE_DECLARATIONS[0].name}) if self.case == 'disabled' else frozenset()
        self.preparation = ConfiguredPreparationRequest(
            ConfiguredHooks(tuple(points), HookSettings()), SUMMARY_CATALOG, disabled)
        self.trust = ConfiguredTrustPolicy(
            (self.sources,), closure_assertions=tuple(assertions),
            python_runtime=ArtifactPythonRuntimeAuthority(executable, digest))
    def _prepare(self):
        """Select external direct Modules without constructing an application owner."""
        if self.case in ('startup', 'disabled'):
            self._prepare_legacy()
            return
        selections = {}
        for point in PHASE_ONE_DECLARATIONS:
            (self.sources / point.name).mkdir(mode=0o700)
            source = self.sources / point.name / 'direct_observer.py'
            source.write_text(
                'import json, os\n'
                'def main(*, hook_context):\n'
                '    """Record detached metadata from the actual direct worker."""\n'
                f'    with open({str(self.ledger)!r}, "a") as stream:\n'
                '        stream.write(json.dumps({"point": hook_context["event_name"], "pid": os.getpid()}) + "\\n")\n'
                + ('    raise RuntimeError("observer fixture failure")\n'
                   if self.case == 'observer_failure' else ''), encoding='utf-8')
            selections[point.name] = {'modules': str(source)}
        hooks.initialize_hook_points(selections)

    def chat(self, configured=True):
        """Use the production AgentChat factory without Hook-specific keywords."""
        chat = agent_shell.get_agent_chat(
            system_prompt='U7 private summary application', agent_name='U7BDD',
            session_id='', message='', tool_map={}, need_input_message=False,
            need_print_session=False, need_set_agent_name_to_thread_local=False,
            need_project_workspace_lock=False)
        self.chats.append(chat)
        return chat

    @staticmethod
    def exit_session(chat):
        """Exercise the real run finalizer via its public message-builder boundary."""
        class SessionBoundary(Exception):
            """Stop only the owned session before any provider request."""

        def stop(**kwargs):
            """Signal session exit from the public input transformation callback."""
            raise SessionBoundary()

        try:
            chat.run(message='U7 session exit', times=2, need_interactive=False,
                     func_build_message=stop)
        except SessionBoundary:
            return
        raise AssertionError('session boundary was not reached')

    def state(self):
        """Read request counts and wire bodies from the provider debug endpoint."""
        with urllib.request.urlopen(
                f'http://127.0.0.1:{self.server.server_port}/debug/state', timeout=5) as response:
            return json.load(response)

    def _observe(self, runtime):
        """Delegate every dispatch to the real executor and record checkpoint state."""
        original = hooks.invoke_hook_point

        def dispatch(name, **kwargs):
            """Observe primary state without replacing configured execution."""
            if self.control:
                return ()
            context = kwargs['hook_context']
            payload = context['payload']
            if 'error__summary_generate' in name:
                self.primary = sys.exception()
                self.generation_traceback = self.primary.__traceback__
            current = runtime.messages if self.layer == 'user2agent' else runtime.ai_agent.messages
            self.events.append((name, dict(payload), context['operation_id'],
                self.state()['total_requests'], list(current), self.application_checked))
            report = original(name, **kwargs)
            self.reports.append(report)
            return report

        self.patch.setattr(hooks, 'invoke_hook_point', dispatch)
        check = runtime._check_summarize_token_reduction

        def accounting(*args, **kwargs):
            """Retain the production accounting check and record its completion."""
            result = check(*args, **kwargs)
            self.application_checked = True
            return result

        self.patch.setattr(runtime, '_check_summarize_token_reduction', accounting)

    def exercise(self):
        """Run startup or a production summary without internal LLM substitution."""
        if self.case == 'unconfigured':
            first = self.chat(False)
            assert not hasattr(first.ctx_runtime_data, 'summary_hooks_executor')
            self.exit_session(first)
        if self.case == 'disabled':
            from topsailai.hooks import configured_preparation
            original = configured_preparation.prepare_private
            self.prepared_names = []

            def prepare(runtime, configuration, scope, **kwargs):
                """Observe exact per-point preparation admissions without replacing I/O."""
                self.prepared_names.extend(p.hook_name for p in configuration.hook_points)
                return original(runtime, configuration, scope, **kwargs)

            self.patch.setattr(configured_preparation, 'prepare_private', prepare)
        chat = self.chat()
        assert not hasattr(chat.ctx_runtime_data, 'summary_hooks_executor')
        if self.case in ('startup', 'disabled'):
            # These assertions cover the retained legacy prepared APIs, not business activation.
            self.owner = legacy_prepared_support.prepared_graph(
                request=self.preparation, trust_policy=self.trust,
                temp_root=str(self.root / 'legacy-runtime'))
            return
        if self.case == 'session':
            second = self.chat()
            self.exit_session(chat)
            assert pending_cleanup() == ()
            chat = second
        runtime = chat.ctx_runtime_data
        self.runtime = runtime
        messages = [
            {'role': 'user', 'content': 'U7 runtime context task'},
            {'role': 'assistant', 'content': 'U7 runtime context details ' * 100},
            {'role': 'user', 'content': 'U7 latest user request'},
        ]
        if self.case == 'empty_input':
            messages = []
        elif self.case == 'feasibility':
            messages = [{'role': 'system', 'content': 'preserved context only'}]
        runtime.messages = list(messages)
        runtime.ai_agent.messages = list(messages)
        self.original_messages = list(messages)
        self._observe(runtime)
        if self.case == 'application_failure':
            self.primary = RuntimeError('U7 application fixture error')

            def fail(*args, **kwargs):
                """Fail only an approved application seam after real generation."""
                assert self.state()['total_requests'] == 1
                raise self.primary

            if self.layer == 'user2agent':
                self.patch.setattr(runtime, 'set_messages', fail)
            else:
                token_stat = runtime.ai_agent.runtime.token_stat
                original_add_msgs = token_stat.add_msgs
                generation_messages = runtime.ai_agent.messages

                def application_add_msgs(messages, *args, **kwargs):
                    """Arm failure only after the rebuilt summary context is published."""
                    if runtime.ai_agent.messages is generation_messages:
                        return original_add_msgs(messages, *args, **kwargs)
                    assert messages is runtime.ai_agent.messages
                    assert any('U7 concise summary' in str(m) for m in messages)
                    return fail(messages, *args, **kwargs)

                self.patch.setattr(token_stat, 'add_msgs', application_add_msgs)
        if self.case == 'human_rejection':
            self.patch.setattr('topsailai.workspace.context.ctx_runtime.input_yes', lambda *a: False)
        try:
            if self.layer == 'user2agent':
                self.result = runtime.summarize_messages_for_processed(
                    force=True, need_interactive=self.case == 'human_rejection')
            else:
                self.result = runtime.summarize_messages_for_processing(force=True)
        except Exception as error:
            self.error = error

    def assert_outcome(self):
        """Assert provider evidence, safe routing, and truthful business outcomes."""
        state = self.state()
        if self.case in ('startup', 'disabled'):
            dispositions = self.owner.startup_report.dispositions
            assert {d.hook_name for d in dispositions} == {p.name for p in PHASE_ONE_DECLARATIONS}
            assert all(d.kind in ('registered', 'disabled_by_configuration') for d in dispositions)
            assert all(d.reason.replace('_', '').isalnum() or d.reason == '' for d in dispositions)
            text = repr(self.owner.startup_report)
            assert str(self.root) not in text and 'Traceback' not in text
            assert not any(p.name in text for p in PHASE_TWO_DECLARATIONS)
            assert state['total_requests'] == 0
            if self.case == 'disabled':
                disabled = next(iter(self.preparation.disabled_hook_names))
                assert next(d for d in dispositions if d.hook_name == disabled).kind == 'disabled_by_configuration'
                assert disabled not in self.prepared_names
                assert any(d.kind == 'registered' for d in dispositions)
            return
        count = 0 if self.case in ('empty_input', 'feasibility') else 1
        assert state['total_requests'] == count, state
        assert len(state['request_bodies']) == count, state
        if count:
            body = state['request_bodies'][0]['body']
            assert body['model'] == 'topsailai-mock-u7'
            text = json.dumps(body['messages'])
            assert 'U7 runtime context' in text
            assert len(body['messages']) > len(self.original_messages)
            assert body['stream'] is True
        names = [event[0] for event in self.events]
        assert all(name.endswith('_' + self.layer) for name in names)
        assert not any('after__summary_generate' in name for name in names)
        assert len({event[2] for event in self.events}) <= 1
        prefix = 'hook__context__'
        before = prefix + 'before__summary_generate_' + self.layer
        if count:
            assert names[0] == before and self.events[0][3] == 0
        if self.case in ('empty_input', 'feasibility', 'human_rejection'):
            assert names == ([before] if count else [])
            assert self.error is None
            assert self.runtime.messages == self.original_messages
            return
        if self.case in ('generation_failure', 'application_failure'):
            assert self.error is not None
            action = 'summary_generate' if self.case == 'generation_failure' else 'summary_apply'
            assert names == [before, prefix + 'error__' + action + '_' + self.layer]
            payload = self.events[-1][1]
            frames = []
            trace = self.error.__traceback__
            while trace:
                frames.append(trace.tb_frame.f_code.co_name)
                trace = trace.tb_next
            if self.case == 'application_failure':
                assert self.error is self.primary and 'fail' in frames
                assert payload['failed_stage'] == ('memory_update' if self.layer == 'user2agent' else 'token_stat_update')
                assert payload['partial_apply_possible'] is True
            else:
                from topsailai.ai_base.llm_control.exception import LLMProviderBadRequestError
                assert isinstance(self.error, LLMProviderBadRequestError)
                assert self.error is self.primary
                trace = self.error.__traceback__
                while trace is not None and trace is not self.generation_traceback:
                    trace = trace.tb_next
                assert trace is self.generation_traceback
                assert '_chat_for_summary' in frames
                assert payload['failed_stage'] == 'generation_request'
            return
        assert self.error is None, self.error
        assert self.result == 'U7 concise summary'
        assert names == [before, prefix + 'after__summary_apply_' + self.layer]
        assert self.events[-1][3] == 1 and self.events[-1][5]
        assert any('U7 concise summary' in str(m) for m in self.events[-1][4])
        rows = [json.loads(row) for row in self.ledger.read_text().splitlines()]
        assert all(row['pid'] != __import__('os').getpid() for row in rows)
        assert pending_cleanup() == ()
        assert [row['point'] for row in rows] == names
        if self.case == 'observer_failure':
            assert any(entry.status == 'error' for report in self.reports for entry in report)
            assert 'observer fixture failure' not in str(self.events)

    def close(self):
        """Close exact resources, then log deletion of only the owned temporary tree."""
        try:
            for chat in self.chats:
                chat.ai_agent.close()
            owner = self.owner
            if owner is not None:
                assert owner.close().fully_closed
        finally:
            if self.server is not None:
                self.server.shutdown()
                self.server.server_close()
            if self.thread is not None:
                self.thread.join(timeout=5)
                assert not self.thread.is_alive()
            default_openai_client_pool.close_all()
            if self.root is not None:
                for path in sorted(self.root.rglob('*'), key=lambda p: len(p.parts), reverse=True):
                    print(f'Deleted U7 scenario artifact: {path}')
                    path.rmdir() if path.is_dir() else path.unlink()
                print(f'Deleted U7 scenario directory: {self.root}')
                self.root.rmdir()
