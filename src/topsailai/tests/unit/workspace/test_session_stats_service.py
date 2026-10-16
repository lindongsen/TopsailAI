"""Focused C acceptance evidence. Author: DawsonLin."""

import json
import logging
import threading
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest

from topsailai.ai_base.agent_runtime import AgentRuntime
from topsailai.context.llm_request_stat import LLMRequestStat
from topsailai.workspace.session_stats_projection import capture, encode, project, UINT, display
from topsailai.context.tool_stat import ToolStat
from topsailai.workspace.session_stats_service import StatsService, ServiceConfig, Binding
from topsailai.utils.thread_local_tool import ctxm_set_agent


class Identity:
    """Plain mutable fixture without statistics changes to Agent/model classes."""

    def __init__(self, **values):
        """Assign ordinary public fields."""
        self.__dict__.update(values)


def deliver(attempt):
    """Use the real execution-thread shortcut for each observation."""
    with ctxm_set_agent(attempt.binding.agent_ref()):
        return attempt.deliver()


def agent():
    """Construct production Tool/Request trackers and a token scalar fixture."""
    token = SimpleNamespace(_id=uuid4().hex, rlock=threading.RLock(),
                            current_count=10, current_completion_count=2,
                            total_count=10, total_completion_count=2,
                            current_cached_tokens=None, total_cached_tokens=0,
                            first_byte_count=0, first_byte_sum_ms=0,
                            first_byte_min_ms=None, first_byte_max_ms=None,
                            _current_count_finalized=False, _current_batch_ticket=1,
                            _completed_batch_ticket=0)
    a = Identity(agent_name='worker', agent_type='react', agent_role='worker',
                 llm_model=Identity(model_name='model-a', tokenStat=token),
                 llm_request_stat=LLMRequestStat())
    a.runtime = AgentRuntime(a)
    return a


def snapshot(a):
    """Prepare identities outside observation and capture via real thread-local state."""
    binding = getattr(a, '_test_binding', None)
    if binding is None:
        binding = Binding(None, a, 'example', None, True)
        a._test_binding = binding
    binding.prepare()
    with ctxm_set_agent(a):
        return capture(binding, session_id='example', writer_id='a'*32,
                       agent_id='b'*32, sequence=1, outcome='success')


def wait_for(predicate):
    """Wait only in the test harness with a bounded failure deadline."""
    end = time.monotonic()+3
    while not predicate():
        assert time.monotonic() < end
        time.sleep(0.005)


def hold(lock):
    """Hold a lock in a separate thread so RLock cannot reenter in capture."""
    entered, release = threading.Event(), threading.Event()
    def run():
        """Own the injected busy boundary until test teardown."""
        with lock:
            entered.set()
            release.wait(3)
    thread = threading.Thread(target=run)
    thread.start()
    assert entered.wait(2)
    return release, thread


def test_projection_and_identity(monkeypatch):
    """Full getters and histories are not observation dependencies."""
    a = agent()
    def poison(*args, **kwargs):
        """Reject any accidental full snapshot, sorting or queue pruning."""
        raise AssertionError('unbounded getter')
    monkeypatch.setattr(a.runtime.tool_stat, '_duration_snapshot_locked', poison)
    monkeypatch.setattr(a.llm_request_stat, '_discard_expired', poison)
    a.runtime.tool_stat._tool_calls = [None]*100000
    r = snapshot(a)
    assert r['tool_stat']['retained_calls'] == 100000
    assert r['tool_stat']['execution_duration_avg_sec'] is None
    assert r['llm_request_stat']['request_duration_min_sec'] is None
    assert r['token_stat']['cached_tokens'] is None
    assert r['token_stat']['uncached_prompt_tokens'] is None
    assert r['token_stat']['first_byte_avg_sec'] is None
    assert r['availability']['token_stat']['pending'] is True
    assert r['availability']['llm_request_stat']['not_computed'] == ['requests_per_minute', 'request_duration_p95_sec']
    assert r['thread_id'] == threading.get_ident()
    token = a.llm_model.tokenStat
    token.first_byte_count, token.first_byte_sum_ms = 2, 500
    token.first_byte_min_ms, token.first_byte_max_ms = 100, 400
    r2 = snapshot(a)
    assert r2['token_stat']['first_byte_avg_sec'] == .25
    assert r2['token_stat']['first_byte_min_sec'] == .1
    a.llm_model.model_name = 'model-b'
    assert snapshot(a)['model_name'] == 'model-b'
    assert snapshot(a)['sources']['token_stat'] == r['sources']['token_stat']
    token.current_count = 1
    assert snapshot(a)['token_stat']['current_prompt_tokens'] == 1
    a.llm_model = Identity(model_name='new-object', tokenStat=token)
    assert snapshot(a)['sources']['model_instance_id'] != r['sources']['model_instance_id']
    assert r['model_name'] == 'model-a'


@pytest.mark.parametrize('target,kind', [('tool', 'tool_stat'), ('token', 'token_stat'), ('request', 'llm_request_stat')])
def test_busy_component(target, kind):
    """Busy whole components are null, not partially projected."""
    a = agent()
    locks = dict(tool=a.runtime.tool_stat._lock, token=a.llm_model.tokenStat.rlock,
                 request=a.llm_request_stat._lock)
    release, thread = hold(locks[target])
    try:
        r = snapshot(a)
        assert r[kind] is None
        assert r['availability'][kind]['state'] == 'busy'
    finally:
        release.set()
        thread.join()


@pytest.mark.parametrize('value', [-1, True, float('nan'), 2**65, 'bad'])
def test_invalid_component(value):
    """Malformed scalars invalidate the whole component."""
    a = agent()
    a.runtime.tool_stat._execution_duration_count = value
    r = snapshot(a)
    assert r['tool_stat'] is None
    assert r['availability']['tool_stat']['state'] == 'invalid'


def test_budget():
    """Worst escaped display values and legal scalar widths fit the line cap."""
    a = agent()
    a.agent_name, a.agent_type, a.llm_model.model_name = '\x01'*64, '\x01'*32, '\x01'*96
    r = snapshot(a)
    for key in ('pid', 'thread_id', 'attempt_seq'):
        r[key] = UINT
    r['session_id'] = 'x'*64
    r['record_id'] = 'a'*32+':'+ 'b'*32+':'+str(UINT)
    for kind in ('tool_stat', 'token_stat', 'llm_request_stat'):
        for key in r[kind]:
            r[kind][key] = 10**15 if key.endswith('_sec') else UINT
    r['diagnostics'] = dict(scope='process_at_capture', **dict.fromkeys(('queue_full','lock_busy','storage_failure','invalid_record'), UINT))
    line = encode(r)
    assert line is not None and len(line) <= 4096 and line.endswith(b'\n')
    assert json.loads(line)['agent_name'] == a.agent_name
    r['agent_name'] = 'x'*5000
    assert encode(r) is None
    assert display('你'*100000, 64) == ('你'*21, 'truncated')
    assert display('\ud800', 64) == (None, 'invalid')


def test_real_persistence_and_release(tmp_path):
    """Real B appends survive peer close and sequential binding reclamation."""
    s = StatsService(diagnostic=lambda *args: True, directory=tmp_path)
    a, peer = agent(), agent()
    try:
        b, other = s.bind(a, 'shared', execution_thread_exclusive=True), s.bind(peer, 'shared', execution_thread_exclusive=True)
        assert deliver(b.begin())
        b.close()
        assert deliver(other.begin())
        for _ in range(80):
            transient = s.bind(a, 'sequential', execution_thread_exclusive=True)
            assert transient is not None
            transient.close()
        path = other.writer.path
        wait_for(lambda: path.exists() and len(path.read_bytes().splitlines()) == 2)
        records = [json.loads(line) for line in path.read_bytes().splitlines()]
        assert len({r['agent_instance_id'] for r in records}) == 2
        assert all(r['thread_id'] == threading.get_ident() for r in records)
    finally:
        s.stop()
        s.worker.join(2)
        assert not s.worker.is_alive()


@pytest.mark.parametrize('outcome', ['failure','back','interrupt'])
def test_one_shot(outcome, tmp_path):
    """Rejected delivery is never retried and success cannot overwrite failure."""
    s = StatsService(diagnostic=lambda *args: True, directory=tmp_path)
    a = agent()
    b = s.bind(a, execution_thread_exclusive=True)
    try:
        attempt = b.begin()
        attempt.determine(outcome)
        attempt.determine('success')
        with s.lock:
            assert not deliver(attempt)
        assert attempt.outcome == outcome and attempt.observed
        assert not deliver(attempt)
        assert not s.queue
    finally:
        s.stop()
        s.worker.join(2)


def test_blocked_diagnostic_and_full_queue(tmp_path):
    """A real blocked injected emit does not block capture or business logging."""
    entered, release = threading.Event(), threading.Event()
    def diagnostic(*args):
        """Block the independent handler until the main flow has progressed."""
        entered.set()
        release.wait(3)
        return True
    class BrokenWriter:
        """Fail storage and drive the actual worker diagnostic path."""
        def __init__(self, *args, **kwargs):
            """Retain only a safe destination primitive."""
            self.path = tmp_path/'broken'
        def append(self, line):
            """Inject a storage failure before diagnostic emission."""
            raise OSError('storage unavailable')
    s = StatsService(diagnostic=diagnostic, directory=tmp_path,
                     config=ServiceConfig(max_records=1), writer_factory=BrokenWriter)
    a = agent()
    b = s.bind(a, execution_thread_exclusive=True)
    try:
        assert deliver(b.begin())
        assert entered.wait(2)
        assert deliver(b.begin())
        assert not deliver(b.begin())
        progressed = []
        class Handler(logging.Handler):
            """Record real business logging before releasing the diagnostic."""
            def emit(self, record):
                """Mark successful main-flow log emission."""
                progressed.append(record.getMessage())
        log = logging.Logger('stats-business-proof')
        log.addHandler(Handler())
        log.warning('business continues')
        assert progressed == ['business continues'] and not release.is_set()
    finally:
        release.set()
        s.stop()
        s.worker.join(2)


def test_identity_lock_busy(tmp_path):
    """Adapter capture contention rejects without waiting."""
    a = agent()
    snapshot(a)
    release, thread = hold(a._test_binding.capture_lock)
    try:
        assert snapshot(a) is None
    finally:
        release.set()
        thread.join()


@pytest.mark.parametrize('kind', ['tool_stat', 'token_stat', 'llm_request_stat'])
def test_projection_invalid_shapes(kind):
    """Invalid zero-sample shapes cannot masquerade as known zero values."""
    a = agent()
    trackers = dict(tool_stat=a.runtime.tool_stat, token_stat=a.llm_model.tokenStat,
                    llm_request_stat=a.llm_request_stat)
    t = trackers[kind]
    if kind == 'tool_stat':
        t._execution_duration_sum_sec = 1
    elif kind == 'token_stat':
        t.first_byte_sum_ms = 1
    else:
        t._request_duration_min_sec = 1
    assert project(t, kind)[2]['state'] == 'invalid'
    assert project(SimpleNamespace(), kind)[2]['state'] == 'invalid'
    assert project(None, kind)[2]['state'] == 'missing'


@pytest.mark.parametrize('value', [float('nan'), -1, True, 'bad', 10**16])
def test_invalid_durations(value):
    """Duration domain violations invalidate a complete block."""
    a = agent()
    a.runtime.tool_stat._execution_duration_sum_sec = value
    assert snapshot(a)['availability']['tool_stat']['state'] == 'invalid'


def test_token_invalid_sum_and_known_cache():
    """Known cache and completed usage are distinct from unknown/pending."""
    a = agent()
    t = a.llm_model.tokenStat
    t.current_cached_tokens = 3
    t._current_count_finalized = True
    t._completed_batch_ticket = 1
    r = snapshot(a)
    assert r['token_stat']['uncached_prompt_tokens'] == 7
    assert r['availability']['token_stat']['pending'] is False
    t.first_byte_sum_ms = float('nan')
    assert snapshot(a)['token_stat'] is None


def test_identity_missing_and_invalid():
    """Missing model/runtime and malformed names preserve explicit statuses."""
    a = agent()
    a.agent_name = None
    a.agent_type = 42
    a.agent_role = 'invalid'
    a.llm_model.model_name = '\ud800'
    r = snapshot(a)
    assert r['availability']['identity']['agent_name'] == 'missing'
    assert r['availability']['identity']['agent_type'] == 'invalid'
    assert r['availability']['identity']['agent_role'] == 'invalid'
    assert r['availability']['token_stat']['state'] == 'invalid'
    a.llm_model = None
    assert snapshot(a)['token_stat'] is None
    assert display('', 64) == (None, 'missing')


def test_binding_caps_idle_and_closed(tmp_path):
    """Dead weak owners, explicit close and sequence overflow release admission."""
    import gc
    s = StatsService(diagnostic=lambda *args: True, directory=tmp_path,
                     config=ServiceConfig(max_bindings=1))
    a = agent()
    try:
        b = s.bind(a, execution_thread_exclusive=True)
        assert s.bind(a, execution_thread_exclusive=True) is None
        b.sequence = UINT
        assert b.begin() is None
        assert b.begin() is None
        next_binding = s.bind(a, execution_thread_exclusive=True)
        assert next_binding is not None
        with s.lock:
            next_binding.close()
        assert s.bind(a, execution_thread_exclusive=True) is not None
        s.bindings[0].closed = True
        orphan = agent()
        dead = s.bind(orphan, execution_thread_exclusive=True)
        del orphan
        gc.collect()
        assert not dead.offer(1, 'success')
        assert s.bind(a, execution_thread_exclusive=True) is not None
    finally:
        s.stop()
        s.worker.join(2)


def test_service_rejection_and_fork_authority(tmp_path, monkeypatch):
    """Inherited services reject before touching locks; byte limits drop offers."""
    import topsailai.workspace.session_stats_service as module
    s = StatsService(diagnostic=lambda *args: True, directory=tmp_path,
                     config=ServiceConfig(max_bytes=1))
    a = agent()
    b = s.bind(a, execution_thread_exclusive=True)
    try:
        assert not deliver(b.begin())
        with pytest.raises(ValueError):
            b.begin().determine('unknown')
        with monkeypatch.context() as m:
            m.setattr(module, 'os', SimpleNamespace(getpid=lambda: s.pid+1))
            assert not b.offer(1, 'success')
            assert s.bind(a, execution_thread_exclusive=True) is None
            s.reclaim()
        s.stop()
        assert not deliver(b.begin())
        assert s.bind(a, execution_thread_exclusive=True) is None
    finally:
        s.stop()
        s.worker.join(2)


def test_bootstrap_and_diagnostic_failure(tmp_path, monkeypatch):
    """Process singleton and fork rebuild never reuse the old worker generation."""
    import topsailai.workspace.session_stats_service as module
    monkeypatch.setattr(module, '_service', None)
    def broken_diagnostic(*args):
        """Fail without forwarding to application logging."""
        raise OSError('independent sink unavailable')
    s = module.process_service(diagnostic=broken_diagnostic, directory=tmp_path)
    rebuilt = None
    try:
        assert module.process_service(diagnostic=broken_diagnostic, directory=tmp_path) is s
        s.pid -= 1
        rebuilt = module.process_service(diagnostic=broken_diagnostic, directory=tmp_path)
        assert rebuilt is not s and rebuilt.writer_id != s.writer_id
        s.stop()
    finally:
        s.stop()
        s.worker.join(2)
        if rebuilt is not None:
            rebuilt.stop()
            rebuilt.worker.join(2)
    assert ServiceConfig(max_records=-1, max_bytes=True, max_bindings=100) == ServiceConfig()


def test_capture_failures_and_nonfinite_encoding(tmp_path, monkeypatch):
    """Capture failure drops once without interrupting business execution."""
    import topsailai.workspace.session_stats_service as module
    import topsailai.workspace.session_stats_projection as projection
    a = agent()
    s = StatsService(diagnostic=lambda *args: True, directory=tmp_path)
    b = s.bind(a, execution_thread_exclusive=True)
    try:
        with monkeypatch.context() as m:
            def broken(*args, **kwargs):
                """Inject a resource-free capture failure."""
                raise ValueError('capture unavailable')
            m.setattr(module, 'capture', broken)
            attempt = b.begin()
            assert not deliver(attempt) and not deliver(attempt)
        with monkeypatch.context() as m:
            m.setattr(projection, 'os', SimpleNamespace(getpid=lambda: 0))
            assert snapshot(a) is None
        with monkeypatch.context() as m:
            m.setattr(projection, 'datetime', SimpleNamespace(now=lambda: SimpleNamespace(astimezone=lambda: SimpleNamespace(isoformat=lambda **kwargs: 'bad'))))
            assert snapshot(a) is None
        with pytest.raises(ValueError):
            encode(dict(value=float('nan')))
    finally:
        s.stop()
        s.worker.join(2)


def test_blocked_storage_and_sink_failure(tmp_path):
    """Blocked append cannot delay producers; a broken diagnostic cannot recurse."""
    entered, release = threading.Event(), threading.Event()
    class Writer:
        """Drive actual worker exception handling after a deterministic stall."""
        def __init__(self, *args, **kwargs):
            """Keep destination detached from the Agent."""
            self.path = tmp_path/'fixture'
        def append(self, line):
            """Stall independently and then fail."""
            entered.set()
            release.wait(3)
            raise OSError('injected')
    called = threading.Event()
    def diagnostic(*args):
        """Prove diagnostic failure remains on the worker only."""
        called.set()
        raise OSError('sink failed')
    s = StatsService(diagnostic=diagnostic, directory=tmp_path, writer_factory=Writer)
    a = agent()
    b = s.bind(a, execution_thread_exclusive=True)
    try:
        assert deliver(b.begin())
        assert entered.wait(2)
        assert deliver(b.begin())
        assert not release.is_set()
        release.set()
        assert called.wait(2)
    finally:
        release.set()
        s.stop()
        s.worker.join(2)


def test_real_identity_class_protocol():
    """Actual Agent/model classes participate without provider construction."""
    from topsailai.ai_base.agent_base import AgentBase
    from topsailai.ai_base.llm_control.base_class import LLMModelBase
    a = AgentBase.__new__(AgentBase)
    a.agent_name, a.agent_type, a.agent_role = 'actual', 'react', 'worker'
    model = LLMModelBase.__new__(LLMModelBase)
    model.model_name, model.tokenStat = 'actual-model', None
    a.llm_model = model
    a.runtime = AgentRuntime(a)
    a.llm_request_stat = LLMRequestStat()
    assert snapshot(a)['model_name'] == 'actual-model'
    model.model_name = 'changed'
    assert snapshot(a)['model_name'] == 'changed'


def test_encode_none_and_nonfinite_number():
    """Explicit drop and nonfinite numeric domains have independent assertions."""
    from topsailai.workspace.session_stats_projection import number
    assert encode(None) is None
    with pytest.raises(ValueError):
        number(float('nan'))


def test_second_worker_rejected(tmp_path):
    """Direct construction cannot bypass the single-writer process premise."""
    s = StatsService(diagnostic=lambda *args: True, directory=tmp_path)
    try:
        with pytest.raises(RuntimeError, match='already owned'):
            StatsService(diagnostic=lambda *args: True, directory=tmp_path)
    finally:
        s.stop()
        s.worker.join(2)


def test_ungranted_and_wrong_thread_drop():
    """No implicit ownership grant, thread-local fallback or model registration."""
    a = agent()
    b = Binding(None, a, 'example', None)
    kwargs = dict(session_id='example', writer_id='a'*32, agent_id='b'*32,
                  sequence=1, outcome='success')
    with ctxm_set_agent(a):
        assert capture(b, **kwargs) is None
    b.exclusive = True
    assert b.prepare()
    assert capture(b, **kwargs) is None
    result = []
    def other_thread():
        """Bind the same Agent on a foreign execution thread."""
        with ctxm_set_agent(a):
            result.append(capture(b, **kwargs))
    t = threading.Thread(target=other_thread)
    t.start()
    t.join(2)
    assert result == [None]
    a.llm_model = Identity(model_name='new', tokenStat=None)
    with ctxm_set_agent(a):
        assert capture(b, **kwargs) is None
        assert b.prepare()
        assert capture(b, **kwargs)['model_name'] == 'new'


def test_model_identity_shared_across_bindings():
    """One model retains its lifetime identity across independent Agent bindings."""
    a, peer = agent(), agent()
    peer.llm_model = a.llm_model
    left = Binding(None, a, 'example', None, True)
    right = Binding(None, peer, 'example', None, True)
    assert left.model_id(a.llm_model) == right.model_id(peer.llm_model)
    for _ in range(64):
        left.models.append((lambda: None, 'x'*32))
    assert left.prepare()
    left.models = [(lambda: a, 'x'*32)]*64
    a.llm_model = Identity(model_name='capacity', tokenStat=None)
    assert not left.prepare()


@pytest.mark.parametrize('kind', ['tool_stat', 'token_stat', 'llm_request_stat'])
@pytest.mark.parametrize('bad_id', [None, 32, b'a'*32, 'A'*32, 'g'*32, 'a'*33, 'a'*100000])
def test_invalid_source_id_before_projection(kind, bad_id):
    """Reject malformed identities before touching tracker locks or metrics."""
    a = agent()
    trackers = dict(tool_stat=a.runtime.tool_stat, token_stat=a.llm_model.tokenStat,
                    llm_request_stat=a.llm_request_stat)
    t = trackers[kind]
    t._id = bad_id
    class PoisonLock:
        """Fail if validation accidentally reaches projection."""
        def acquire(self, **kwargs):
            """No malformed identity may authorize metric access."""
            raise AssertionError('invalid source reached lock')
    setattr(t, 'rlock' if kind == 'token_stat' else '_lock', PoisonLock())
    r = snapshot(a)
    assert r['sources'][kind] is None and r[kind] is None
    assert r['availability'][kind]['state'] == 'invalid'
    assert json.loads(encode(r))['sources'][kind] is None


@pytest.mark.parametrize('entry', ['direct', 'process'])
def test_starting_worker_retains_authority(tmp_path, monkeypatch, entry):
    """Pause real Thread.start before launch and reject both second entrances."""
    import topsailai.workspace.session_stats_service as module
    monkeypatch.setattr(module, '_service', None)
    entered, release = threading.Event(), threading.Event()
    original = threading.Thread.start
    created, errors = [], []
    def paused_start(thread):
        """Expose the assigned-but-not-started worker window deterministically."""
        if thread.name == 'session-stats':
            entered.set()
            assert release.wait(3)
        return original(thread)
    def construct():
        """Create the first service outside the test's execution thread."""
        try:
            created.append(StatsService(diagnostic=lambda *args: True, directory=tmp_path))
        except BaseException as exc:
            errors.append(exc)
    monkeypatch.setattr(threading.Thread, 'start', paused_start)
    constructor = threading.Thread(target=construct)
    constructor.start()
    try:
        assert entered.wait(2)
        factory = StatsService if entry == 'direct' else module.process_service
        with pytest.raises(RuntimeError, match='already owned'):
            factory(diagnostic=lambda *args: True, directory=tmp_path)
    finally:
        release.set()
        constructor.join(3)
        for service in created:
            service.stop()
            service.worker.join(2)
    assert not errors and len(created) == 1 and not constructor.is_alive()
    replacement = module.process_service(diagnostic=lambda *args: True, directory=tmp_path)
    replacement.stop()
    replacement.worker.join(2)


@pytest.mark.parametrize('launched', [False, True])
def test_failed_startup_releases_only_safe_authority(tmp_path, monkeypatch, launched):
    """Initialization errors retire safely, including errors after real launch."""
    entered, release = threading.Event(), threading.Event()
    original = threading.Thread.start
    failed = []
    def work(service):
        """Hold an already launched worker alive after start reports failure."""
        entered.set()
        assert release.wait(3)
    def broken_start(thread):
        """Fail either before launch or after the worker entered real execution."""
        failed.append(thread)
        if launched:
            original(thread)
            assert entered.wait(2)
        raise RuntimeError('startup failed')
    with monkeypatch.context() as patch:
        patch.setattr(StatsService, '_work', work)
        patch.setattr(threading.Thread, 'start', broken_start)
        try:
            with pytest.raises(RuntimeError, match='startup failed'):
                StatsService(diagnostic=lambda *args: True, directory=tmp_path)
            if launched:
                with pytest.raises(RuntimeError, match='already owned'):
                    StatsService(diagnostic=lambda *args: True, directory=tmp_path)
        finally:
            release.set()
            if launched:
                failed[0].join(2)
    replacement = StatsService(diagnostic=lambda *args: True, directory=tmp_path)
    replacement.stop()
    replacement.worker.join(2)


def test_stopping_worker_cannot_be_replaced(tmp_path, monkeypatch):
    """Retirement requires actual thread exit for direct and shared entrances."""
    import topsailai.workspace.session_stats_service as module
    entered, release = threading.Event(), threading.Event()
    def work(service):
        """Keep the old worker alive despite its retirement request."""
        entered.set()
        assert release.wait(3)
    monkeypatch.setattr(module, '_service', None)
    with monkeypatch.context() as patch:
        patch.setattr(StatsService, '_work', work)
        s = module.process_service(diagnostic=lambda *args: True, directory=tmp_path)
        try:
            assert entered.wait(2)
            s.stop()
            with pytest.raises(RuntimeError):
                StatsService(diagnostic=lambda *args: True, directory=tmp_path)
            with pytest.raises(RuntimeError, match='not retired'):
                module.process_service(diagnostic=lambda *args: True, directory=tmp_path)
        finally:
            release.set()
            s.worker.join(2)
    replacement = module.process_service(diagnostic=lambda *args: True, directory=tmp_path)
    assert replacement is not s
    replacement.stop()
    replacement.worker.join(2)


def test_real_token_tracker_projection():
    """Project a real initialized TokenStat and stop its owned background thread."""
    from topsailai.context.token import TokenStat
    token = TokenStat('session-stats-test')
    try:
        with token.rlock:
            token.first_byte_count, token.first_byte_sum_ms = 2, 500
            token.first_byte_min_ms, token.first_byte_max_ms = 100, 400
            source, values, status = project(token, 'token_stat')
        assert source == token._id and status['state'] == 'available'
        assert values['first_byte_avg_sec'] == .25
        assert values['first_byte_min_sec'] == .1 and values['first_byte_max_sec'] == .4
    finally:
        token.flag_running = False
        token.join(3)
        assert not token.is_alive()


def test_failed_worker_late_start_is_disarmed(tmp_path, monkeypatch):
    """A thread retained by failed startup cannot later enter the write loop."""
    threads, writes = [], []
    def fail_start(thread):
        """Retain the unstarted thread as an adversarial delayed launcher."""
        threads.append(thread)
        raise RuntimeError('delayed startup failure')
    with monkeypatch.context() as patch:
        patch.setattr(threading.Thread, 'start', fail_start)
        with pytest.raises(RuntimeError, match='delayed startup failure'):
            StatsService(diagnostic=lambda *args: True, directory=tmp_path)
    monkeypatch.setattr(StatsService, '_work', lambda service: writes.append(service))
    threads[0].start()
    threads[0].join(2)
    assert not threads[0].is_alive() and writes == []
