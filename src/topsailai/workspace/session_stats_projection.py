"""Fixed-work, detached session statistics projection. Author: DawsonLin."""

import json
import math
import os
import threading
from datetime import datetime

UINT = 2**64 - 1
OMITTED = {
    'tool_stat': ['retained_errors', 'success_rate', 'execution_duration_p95_sec', 'per_tool'],
    'token_stat': [],
    'llm_request_stat': ['requests_per_minute', 'request_duration_p95_sec'],
}


def display(value, cap):
    """Bound a display field without coercion or unbounded Unicode inspection."""
    if value is None:
        return None, 'missing'
    if type(value) is not str:
        return None, 'invalid'
    if value == '':
        return None, 'missing'
    try:
        prefix = value[:cap + 1].encode('utf-8')
        text = prefix[:cap].decode('utf-8', errors='ignore')
        return text, 'truncated' if len(prefix) > cap else 'available'
    except UnicodeError:
        return None, 'invalid'


def integer(value):
    """Validate an unsigned scalar without accepting booleans."""
    if type(value) is not int or not 0 <= value <= UINT:
        raise ValueError('invalid integer')
    return value


def number(value):
    """Validate and round finite duration seconds."""
    if type(value) not in (int, float) or not 0 <= value <= 10**15:
        raise ValueError('invalid duration')
    if not math.isfinite(value):
        raise ValueError('nonfinite duration')
    return round(value, 3)


def tool_values(t):
    """Copy constant-cost duration accumulators and retained-list length only."""
    count = integer(t._execution_duration_count)
    total = number(t._execution_duration_sum_sec)
    if count == 0 and total != 0:
        raise ValueError('inconsistent zero samples')
    return dict(retained_calls=integer(len(t._tool_calls)),
                execution_duration_count=count, execution_duration_sum_sec=total,
                execution_duration_avg_sec=number(t._execution_duration_sum_sec / count) if count else None)


def token_values(t):
    """Preserve TokenStat seconds, unknown cache and provisional batch semantics."""
    p, c = integer(t.current_count), integer(t.current_completion_count)
    tp, tc = integer(t.total_count), integer(t.total_completion_count)
    cached = None if t.current_cached_tokens is None else integer(t.current_cached_tokens)
    result = dict(current_prompt_tokens=p, current_completion_tokens=c,
                  current_total_tokens=integer(p+c), cached_tokens=cached,
                  uncached_prompt_tokens=None if cached is None else max(0, p-cached),
                  total_prompt_tokens=tp, total_completion_tokens=tc,
                  total_usage_tokens=integer(tp+tc), total_cached_tokens=integer(t.total_cached_tokens))
    count = integer(t.first_byte_count)
    total = t.first_byte_sum_ms
    if type(total) not in (int, float) or total < 0 or not math.isfinite(total):
        raise ValueError('invalid first byte sum')
    if not count and (total != 0 or t.first_byte_min_ms is not None or t.first_byte_max_ms is not None):
        raise ValueError('inconsistent first byte samples')
    for name, value in (('avg', total/count if count else None),
                        ('min', t.first_byte_min_ms), ('max', t.first_byte_max_ms)):
        result[f'first_byte_{name}_sec'] = number(value/1000) if count else None
    pending = (not t._current_count_finalized or
               (t._current_batch_ticket is not None and
                t._completed_batch_ticket < t._current_batch_ticket))
    return result, bool(pending)


def request_values(t):
    """Read scalar counters without expiry pruning or percentile sorting."""
    names = ('total_requests', 'request_successes', 'request_failures',
             'response_content_errors', 'requests_per_minute_max', 'request_duration_count')
    result = {name: integer(getattr(t, '_'+name)) for name in names}
    count = result['request_duration_count']
    total = number(t._request_duration_sum_sec)
    lo, hi = t._request_duration_min_sec, t._request_duration_max_sec
    if not count and (total != 0 or lo is not None or hi is not None):
        raise ValueError('inconsistent request samples')
    for name, value in (('min', lo), ('avg', t._request_duration_sum_sec/count if count else None), ('max', hi)):
        result[f'request_duration_{name}_sec'] = number(value) if count else None
    return result


def valid_source_id(value):
    """Inspect at most 32 exact string characters before projection or encoding."""
    return (type(value) is str and len(value) == 32
            and all(c in '0123456789abcdef' for c in value))


def project(tracker, kind):
    """Try one tracker lock; never wait or acquire another tracker lock."""
    status = dict(state='missing', pending=None, not_computed=OMITTED[kind].copy())
    if tracker is None:
        return None, None, status
    source = getattr(tracker, '_id', None)
    lock = getattr(tracker, 'rlock' if kind == 'token_stat' else '_lock', None)
    if not valid_source_id(source) or lock is None:
        status['state'] = 'invalid'
        return None, None, status
    if not lock.acquire(blocking=False):
        status['state'] = 'busy'
        return source, None, status
    try:
        pending = None
        if kind == 'token_stat':
            values, pending = token_values(tracker)
        else:
            values = tool_values(tracker) if kind == 'tool_stat' else request_values(tracker)
        status.update(state='available', pending=pending)
        return source, values, status
    except (ValueError, TypeError, AttributeError, OverflowError):
        status['state'] = 'invalid'
        return source, None, status
    finally:
        lock.release()


def capture(binding, *, session_id, writer_id, agent_id, sequence, outcome, settle=False):
    """Pin snapshot references; settlement needs ownership, not model exclusivity."""
    agent = binding.agent_ref()
    authorize = binding.settle_authorized if settle else binding.authorized
    if not authorize(agent):
        return None
    if not binding.capture_lock.acquire(blocking=False):
        return None
    try:
        runtime = agent.runtime
        model = runtime.llm_model
        tool = runtime.tool_stat
        token = model.tokenStat if model is not None else None
        request = agent.llm_request_stat
        model_id = binding.model_id(model)
        if model is not None and model_id is None:
            return None
        identity, fields = {}, {}
        for key, cap in (('agent_name', 64), ('agent_type', 32)):
            fields[key], identity[key] = display(getattr(agent, key, None), cap)
        role = getattr(agent, 'agent_role', None)
        fields['agent_role'] = role if type(role) is str and role in ('manager', 'worker') else None
        identity['agent_role'] = 'available' if fields['agent_role'] else ('missing' if role is None or role == '' else 'invalid')
        fields['model_name'], identity['model_name'] = display(model.model_name, 96) if model is not None else (None, 'missing')
        sources = dict(scope='current_tracker_snapshot', model_instance_id=model_id)
        availability = dict(identity=identity)
        usable_token = token if fields['model_name'] is not None else None
        for kind, tracker in (('tool_stat', tool), ('token_stat', usable_token), ('llm_request_stat', request)):
            sources[kind], fields[kind], availability[kind] = project(tracker, kind)
        if model is not None and fields['model_name'] is None:
            availability['token_stat']['state'] = identity['model_name']
        pid, tid = integer(os.getpid()), integer(threading.get_ident())
        if not pid or not tid:
            return None
        stamp = datetime.now().astimezone().isoformat(timespec='microseconds')
        if len(stamp) != 32:
            return None
        return dict(schema_version=1, record_id=f'{writer_id}:{agent_id}:{sequence}',
                    session_id=session_id, pid=pid, thread_id=tid,
                    writer_instance_id=writer_id, agent_instance_id=agent_id,
                    current_time=stamp, attempt_seq=sequence, outcome=outcome,
                    sources=sources, availability=availability, diagnostics=None, **fields)
    finally:
        binding.capture_lock.release()


def encode(record):
    """Encode adapter-constructed records, not arbitrary external schema input.

    Capture constructs keys, identities, statuses and bounded scalar blocks;
    project validates source IDs before any metric read. This final boundary
    enforces strict JSON and byte capacity, not standalone schema validation.
    """
    if record is None:
        return None
    line = (json.dumps(record, ensure_ascii=False, allow_nan=False,
                       separators=(',', ':'))+'\n').encode('utf-8')
    return line if len(line) <= 4096 else None
