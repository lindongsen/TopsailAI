"""Mixed Script deployment and real summary acceptance. Author: DawsonLin."""

import copy
import hashlib
import json
import os
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import urllib.request
from pathlib import Path

from tests.mock.llm_mock_server import MockServerConfig, create_server
from tests.bdd.summarize_hooks_harness import SummarizeHooksScenario
from topsailai.ai_base.llm_pool.openai_client_pool import default_openai_client_pool
from topsailai.hooks import ArtifactPythonRuntimeAuthority, HookSettings
from topsailai.hooks.configuration import HookLimits
from topsailai.hooks.configured_bootstrap import load_configured_trust_manifest
from topsailai.hooks.deployment_script_authorization import write_mixed_trust_manifest
from topsailai.hooks.hook_script_discovery import ExecutablePlatformPolicy
from topsailai.hooks.points.catalog import PHASE_ONE_DECLARATIONS
import topsailai.hooks as hooks
from topsailai.hooks.point_entry import pending_cleanup
from topsailai.workspace import agent_shell
from tests import legacy_prepared_support


class MixedDeployment:
    """Own only fixture sources, offline authority and composed application lifetimes."""

    def __init__(self, root, fault="success", settings=None):
        """Create reverse-ordered members without executing or authorizing them yet."""
        self.root, self.fault = root, fault
        self.points = root / "points"
        self.points.mkdir(mode=0o700)
        self.ledger = root / "observations.jsonl"
        self.executable = Path(sys.executable).resolve(strict=True)
        self.digest = hashlib.sha256(self.executable.read_bytes()).hexdigest()
        self.policy = ExecutablePlatformPolicy("posix", (str(self.executable),))
        self.settings = settings or HookSettings(limits=HookLimits(
            handler_timeout_ms=2250, dispatch_timeout_ms=4750))
        self.owners = []
        self.serial = 0
        for point in self.request().configuration.hook_points:
            point.module_folder.mkdir(parents=True, mode=0o700)
            for name in ("zeta", "Alpha"):
                (point.module_folder / (name + ".py")).write_text(f'''
import json, os
from topsailai.hooks.contracts import _thaw_frozen_json

def main(*, hook_context):
    """Record only safe detached metadata from a real worker."""
    hook_context = _thaw_frozen_json(hook_context)
    row = {{'name': {name!r}, 'pid': os.getpid(), 'point': hook_context['event_name'], 'payload': hook_context['payload']}}
    with open({str(self.ledger)!r}, 'a') as stream:
        stream.write(json.dumps(row) + '\\n')
    return False
''')
            for name in ("z", "A"):
                self.add_script(point, name)

    def request(self):
        """Select fixed point-local paths without scanning or generating authority."""
        return legacy_prepared_support.build_summary_preparation_request(
            points_root=self.points, settings=self.settings, script_platform_policy=self.policy)

    def add_script(self, point, name):
        """Create a protocol-compliant executable with safe worker identity evidence."""
        folder = point.module_folder.parent / "scripts"
        folder.mkdir(mode=0o700, exist_ok=True)
        path = folder / name
        fault = self.fault if name == "A" else "success"
        failure = "raise RuntimeError('fixture Script failure')" if fault in ("script_failure", "generation_failure", "application_failure", "empty_provider_exhaustion") else ""
        blocking = "time.sleep(60)" if fault == "blocked" else ""
        path.write_text(f'''#!{self.executable}
import json, os, struct, sys, time
request = json.loads(sys.stdin.buffer.read())
event = request['context']['event']
row = {{'name': {name!r}, 'pid': os.getpid(), 'point': event['name'], 'payload': event['payload']}}
with open({str(self.ledger)!r}, 'a') as stream:
    stream.write(json.dumps(row) + '\\n')
{failure}
{blocking}
result = {{key: request[key] for key in ('protocol_version', 'delivery_id', 'invocation_id', 'entry_index')}}
result['value'] = {{'error': 1}}
body = json.dumps(result).encode()
os.write(int(os.environ['TOPSAILAI_HOOK_RESULT_FD']), struct.pack('!I', len(body)) + body)
''')
        path.chmod(0o700)
        return path

    def authorize(self):
        """Generate exclusive offline authority and load it through its public pin."""
        request = self.request()
        output = self.root / f"manifest-{self.serial}.json"
        self.serial += 1
        pin = write_mixed_trust_manifest(output,
            module_folders=tuple(p.module_folder for p in request.configuration.hook_points),
            scripts=tuple(p.script for p in request.configuration.hook_points),
            source_roots=(self.points,), reviewed_deployment_sha256="a" * 64,
            python_runtime=ArtifactPythonRuntimeAuthority(self.executable, self.digest),
            interpreter_digests=((self.executable, self.digest),))
        return load_configured_trust_manifest(output, pin)[0]

    def start(self, trust=None):
        """Register eagerly through the real application owner and retain cleanup custody."""
        trust = self.authorize() if trust is None else trust
        root = self.root / f"runtime-{len(self.owners)}"
        root.mkdir(mode=0o700)
        owner = legacy_prepared_support.prepared_graph(request=self.request(),
            trust_policy=trust, temp_root=str(root))
        self.owners.append(owner)
        return owner

    def rows(self):
        """Read bounded test ledger entries written only at business handler entry."""
        return [json.loads(line) for line in self.ledger.read_text().splitlines()] if self.ledger.exists() else []

    def close(self):
        """Require honest owner close and confirmed absence of observed workers."""
        for owner in self.owners:
            result = owner.close()
            assert result.fully_closed and not result.unresolved_debts and not result.failed_stages
            assert not owner.runtime.cleanup_debts()
        for row in self.rows():
            assert row["pid"] != os.getpid()
            try:
                os.kill(row["pid"], 0)
            except ProcessLookupError:
                continue
            raise AssertionError(f"observed fixture worker still exists: {row['pid']}")


class DirectDeployment(MixedDeployment):
    """Reuse fixture membership while selecting direct resources without authority."""

    def __init__(self, root, fault="success"):
        """Build actual Modules and directly executable Scripts for each point."""
        super().__init__(root, fault)
        self.config = {p.hook_name: {
            "modules": str(p.module_folder),
            "scripts": str(p.module_folder.parent / "scripts"),
        } for p in self.request().configuration.hook_points}

    def request(self):
        """Describe fixture directories without using the legacy owner builder."""
        points = []
        for declaration in PHASE_ONE_DECLARATIONS:
            _, domain, phase, action = declaration.name.split("__")
            points.append(SimpleNamespace(hook_name=declaration.name,
                module_folder=self.points / domain / f"{phase}_{action}" / "modules"))
        return SimpleNamespace(configuration=SimpleNamespace(hook_points=tuple(points)))

    def add_script(self, point, name):
        """Write a direct executable; no stdin protocol or metadata is supplied."""
        folder = point.module_folder.parent / "scripts"
        folder.mkdir(mode=0o700, exist_ok=True)
        path = folder / name
        failure = (name == "A" and self.fault in (
            "script_failure", "generation_failure", "application_failure",
            "empty_provider_exhaustion"))
        path.write_text(f'''#!{self.executable}
import json, os, sys, time
assert sys.stdin.buffer.read() == b""
row = {{"name": {name!r}, "pid": os.getpid(), "point": {point.hook_name!r}}}
with open({str(self.ledger)!r}, "a") as stream:
    stream.write(json.dumps(row) + "\\n")
{ "raise RuntimeError('fixture Script failure')" if failure else "" }
{ "time.sleep(60)" if self.fault == "blocked" and name == "A" else "" }
''')
        path.chmod(0o700)
        return path

    def close(self):
        """Require exact direct-runner custody to be settled before artifact cleanup."""
        assert pending_cleanup() == ()
        super().close()


class SummaryScriptScenario(SummarizeHooksScenario):
    """Reuse real business interactions, not the legacy fixed-root trust constructor."""
    def __init__(self, monkeypatch, request, layer, case, transport, root, mode="runtime"):
        """Register cleanup before allocating resources or executing a scenario."""
        assert transport == "sse", "Summary acceptance requires real SSE over HTTP"
        self.mode = mode
        self.stores = []
        self.patch = monkeypatch
        self.layer, self.case, self.transport = layer, case, transport
        self.chats, self.events, self.reports = [], [], []
        self.owner = self.server = self.thread = self.root = None
        self.result = self.error = self.primary = None
        self.application_checked = False
        request.addfinalizer(self.close)
        base = root
        base.mkdir(parents=True, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix='scenario-', dir=base))
        self.sources = self.root / 'sources'
        self.sources.mkdir(mode=0o700)
        self.ledger = self.root / 'observer.jsonl'
        reply = '' if case == 'empty_provider_exhaustion' else 'U7 concise summary'
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
            'LLM_RESPONSE_STREAM': '1',
            'TOPSAILAI_CONTEXT_SUMMARY_MODE': mode,
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
        self.retry_delays = []
        if case == "empty_provider_exhaustion":
            from topsailai.ai_base import llm_base
            clock = SimpleNamespace(**{name: getattr(time, name) for name in dir(time)})
            clock.sleep = self.retry_delays.append
            monkeypatch.setattr(llm_base, "time", clock)
        monkeypatch.setattr(hooks, '_point_configuration', ())
        self.control = False
        self._prepare()

    def _prepare(self):
        """Configure direct external Modules and Scripts without owner or trust plumbing."""
        self.deployment = DirectDeployment(self.root, self.case)
        self.ledger = self.deployment.ledger
        self.inputs = {}
        if self.case == "stale":
            # Direct discovery deliberately observes membership added after configuration.
            point = self.deployment.request().configuration.hook_points[0]
            self.deployment.add_script(point, "new")
        hooks.initialize_hook_points(self.deployment.config)

    def _observe(self, runtime):
        """Seed a private persistent session before the real summary checkpoint."""
        if self.case == "session":
            for index, message in enumerate(self.original_messages):
                message["create_time"] = f"2026-01-01 00:00:0{index}"
            from topsailai.context import ctx_manager
            from topsailai.context.session_manager.sql import SessionSQLAlchemy
            store = SessionSQLAlchemy("sqlite:///" + str(self.root / "session.db"))
            self.stores.append(store)
            self.patch.setattr(ctx_manager, "get_session_manager", lambda **kw: store)
            self.patch.setattr(ctx_manager, "get_managers_by_env", lambda *a, **kw: [store.chat_history])
            runtime.session_id = "mixed-session"
            ctx_manager.create_session(runtime.session_id, "private test", session_name="fixture", session_mgr=store)
            for message in self.original_messages:
                ctx_manager.add_session_message(runtime.session_id, message)
            assert ctx_manager.get_messages_by_session(runtime.session_id) == self.original_messages
        self.original_add_msgs = runtime.ai_agent.runtime.token_stat.add_msgs
        self.initial_tokens = self.token_counters(runtime.ai_agent.runtime.token_stat)
        super()._observe(runtime)

    @staticmethod
    def token_counters(stat):
        """Wait for accounting and snapshot counters without copying thread resources."""
        assert stat.wait(stat._current_batch_ticket, timeout=5)
        fields = ("total_count", "current_count", "current_local_count",
            "current_response_count", "current_count_source", "total_completion_count",
            "current_completion_count", "total_text_len", "current_text_len", "msg_count",
            "total_cached_tokens", "current_cached_tokens")
        with stat.rlock:
            return {name: getattr(stat, name) for name in fields}

    @staticmethod
    def stable_history(messages):
        """Exclude only generated creation timestamps, retaining all other fields."""
        return [{key: value for key, value in message.items() if key != "create_time"}
            for message in messages]

    def exercise(self):
        """Compare real business execution with an otherwise identical disabled control."""
        super().exercise()
        self.observed_delays = list(self.retry_delays)
        self.observed_tokens = self.token_counters(self.runtime.ai_agent.runtime.token_stat)
        self.observed_state = copy.deepcopy(self.state())
        self.observed_history = copy.deepcopy(self.runtime.messages if self.layer == "user2agent"
            else self.runtime.ai_agent.messages)
        if self.case == "session":
            from topsailai.context import ctx_manager
            self.persisted_history = ctx_manager.get_messages_by_session(self.runtime.session_id)
            assert self.persisted_history == self.observed_history
            assert len(self.persisted_history) < len(self.original_messages)
            assert not any("runtime context details" in str(m) for m in self.persisted_history)
        runtime = self.runtime
        self.control = True
        stat = runtime.ai_agent.runtime.token_stat
        with stat.rlock:
            for name, value in self.initial_tokens.items():
                setattr(stat, name, value)
        runtime.messages = copy.deepcopy(self.original_messages)
        runtime.ai_agent.messages = copy.deepcopy(self.original_messages)
        if self.case == "session":
            runtime.session_id = "control-session"
            ctx_manager.create_session(runtime.session_id, "private control", session_name="fixture")
            for message in self.original_messages:
                ctx_manager.add_session_message(runtime.session_id, message)
        control_primary = RuntimeError("U7 application fixture error")
        if self.case == "application_failure":
            token_stat = runtime.ai_agent.runtime.token_stat
            generation_messages = runtime.ai_agent.messages

            def control_fail(*args, **kwargs):
                """Rearm the same application boundary for the disabled execution."""
                assert self.state()["total_requests"] == 1
                raise control_primary

            if self.layer == "user2agent":
                self.patch.setattr(runtime, "set_messages", control_fail)
            else:
                original_add_msgs = self.original_add_msgs

                def control_add_msgs(messages, *args, **kwargs):
                    """Fail after control reconstruction, not during provider accounting."""
                    if runtime.ai_agent.messages is generation_messages:
                        return original_add_msgs(messages, *args, **kwargs)
                    assert messages is runtime.ai_agent.messages
                    assert any("U7 concise summary" in str(m) for m in messages)
                    return control_fail(messages, *args, **kwargs)

                self.patch.setattr(token_stat, "add_msgs", control_add_msgs)
        reset = urllib.request.Request(
            f"http://127.0.0.1:{self.server.server_port}/debug/state", method="DELETE")
        with urllib.request.urlopen(reset, timeout=5) as response:
            assert json.load(response) == {"status": "cleared"}
        assert self.state()["total_requests"] == 0
        before = len(self.state()["request_bodies"])
        self.retry_delays.clear()
        control_error = None
        try:
            if self.layer == "user2agent":
                control = runtime.summarize_messages_for_processed(force=True,
                    need_interactive=self.case == "human_rejection")
            else:
                control = runtime.summarize_messages_for_processing(force=True)
        except Exception as error:
            control_error, control = error, None
        if self.case == "empty_provider_exhaustion":
            self.assert_exhaustion(control_error)
            assert self.retry_delays == self.observed_delays == list(range(5, 90, 5))
        elif self.case in ("generation_failure", "application_failure"):
            assert type(control_error) is type(self.error)
            assert control_error.args == self.error.args
            if self.case == "application_failure":
                assert control_error is control_primary and control_error is not self.error
                frames = []
                trace = control_error.__traceback__
                while trace:
                    frames.append(trace.tb_frame.f_code.co_name)
                    trace = trace.tb_next
                assert "control_fail" in frames
        else:
            assert control_error is None
        assert control == self.result
        history = runtime.messages if self.layer == "user2agent" else runtime.ai_agent.messages
        assert self.stable_history(history) == self.stable_history(self.observed_history)
        if self.case == "session":
            control_persisted = ctx_manager.get_messages_by_session(runtime.session_id)
            assert control_persisted == history
            assert self.stable_history(control_persisted) == self.stable_history(self.persisted_history)
            assert ctx_manager.get_messages_by_session("mixed-session") == self.persisted_history
        control_tokens = self.token_counters(stat)
        assert control_tokens == self.observed_tokens, (control_tokens, self.observed_tokens)
        bodies = self.state()["request_bodies"]
        assert self.state()["total_requests"] == self.observed_state["total_requests"]
        assert len(bodies) - before == len(self.observed_state["request_bodies"])
        assert [r["body"] for r in bodies[before:]] == [r["body"]
            for r in self.observed_state["request_bodies"]]
        runtime.messages = copy.deepcopy(self.observed_history)
        if self.layer == "agent2llm":
            runtime.ai_agent.messages = copy.deepcopy(self.observed_history)

    def _assert_business(self):
        """Assert provider evidence, safe routing, and truthful business outcomes."""
        state = self.observed_state
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
        count = (18 if self.case == 'empty_provider_exhaustion' else
            0 if self.case in ('empty_input', 'feasibility') else 1)
        assert state['total_requests'] == count, state
        assert len(state['request_bodies']) == count, state
        if count:
            body = state['request_bodies'][0]['body']
            assert body['model'] == 'topsailai-mock-u7'
            text = json.dumps(body['messages'])
            assert 'U7 runtime context' in text
            if self.mode == "message":
                users = [m for m in body["messages"] if m["role"] == "user"]
                assert len(users) == 1
                assert "Summarize Messages" in users[0]["content"]
                encoded = users[0]["content"].split("---", 2)[-1].strip()
                assert json.loads(encoded) == self.original_messages
            else:
                assert len(body["messages"]) > len(self.original_messages)
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
        if self.case in ('generation_failure', 'application_failure', 'empty_provider_exhaustion'):
            assert self.error is not None
            action = 'summary_apply' if self.case == 'application_failure' else 'summary_generate'
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
                if self.case == "empty_provider_exhaustion":
                    self.assert_exhaustion(self.error)
                    assert self.observed_delays == list(range(5, 90, 5))
                    assert self.stable_history(self.observed_history) == self.stable_history(self.original_messages)
                    assert all(row["body"]["stream"] is True for row in state["request_bodies"])
                else:
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
        assert list(dict.fromkeys(row['point'] for row in rows)) == names
        if self.case == 'observer_failure':
            assert any(r.status == "error" for report in self.reports for r in report)
            assert 'observer fixture failure' not in str(self.events)


    def assert_outcome(self):
        """Assert business checkpoints, real Script order and metadata-only isolation."""
        self._assert_business()
        rows = self.deployment.rows()
        for name in {row["point"] for row in rows}:
            selected = [r for r in rows if r["point"] == name]
            expected = ["Alpha", "zeta", "A", "z"]
            if self.case == "stale" and name == PHASE_ONE_DECLARATIONS[0].name:
                expected = ["Alpha", "zeta", "A", "new", "z"]
            assert [r["name"] for r in selected] == expected
            assert all(r["pid"] != os.getpid() for r in selected)
            assert all("U7 runtime context" not in json.dumps(r) for r in selected)
            assert all("payload" not in r for r in selected if r["name"] in ("A", "z", "new"))
        for report in self.reports:
            modules = [r.name for r in report if r.kind == "module"]
            assert modules == ["Alpha.py", "observer.py", "zeta.py"]
            assert [r.kind for r in report] == sorted(
                (r.kind for r in report), key=lambda kind: kind != "module")
        if self.case in ("generation_failure", "application_failure", "empty_provider_exhaustion"):
            assert len(self.events) == len(self.reports) == 2
            point_name, _, operation_id, *_ = self.events[-1]
            assert "__error__" in point_name
            failed = next(r for r in self.reports[-1] if r.name == "A")
            assert failed.status == "error"
            observed = [row for row in rows if row["point"] == point_name]
            assert [row["name"] for row in observed] == ["Alpha", "zeta", "A", "z"]
            assert all(row["payload"]["operation_id"] == operation_id
                for row in observed if "payload" in row)
        elif self.case == "script_failure":
            assert any(r.status == "error" for report in self.reports for r in report)
        assert pending_cleanup() == ()

    @staticmethod
    def assert_exhaustion(error):
        """Validate the real provider retry contract, not a successful empty skip."""
        from topsailai.ai_base.exception import LLMRetryExhaustedError
        assert isinstance(error, LLMRetryExhaustedError)
        assert error.attempts == 18 and error.manual_cycle_count == 0
        assert error.retry_reason == "type_error"
        assert isinstance(error.last_error, TypeError)
        assert error.__cause__ is error.last_error
        assert error.last_error.args == ("null of response",)

    def close(self):
        """Verify worker settlement before inherited exact server/client/artifact cleanup."""
        if self.owner is not None:
            assert self.owner.close().fully_closed
        if hasattr(self, "deployment"):
            self.deployment.close()
        for store in self.stores:
            store.chat_history.engine.dispose()
            store.engine.dispose()
        super().close()
