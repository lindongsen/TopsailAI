---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
references:
  - /TopsailAI/src/topsailai/ai_base/agent_types/tool.py
  - /TopsailAI/src/topsailai/env_template
  - /TopsailAI/src/topsailai/docs/Environment_Variables.md
---

# Feature: Tool Approval Mechanism

## Overview

Introduce a `tool_approval` mechanism that intervenes at the single-tool execution entry point `exec_tool_func` in `ai_base/agent_types/tool.py`. Before a tool function is actually invoked, the mechanism evaluates whether the call requires explicit human approval. All approval logic is encapsulated in a per-call `ToolApprovalInstance`; the original `exec_tool_func` implementation is left untouched and is only wrapped by a decorator.

## Goals

1. Provide a centralized, configuration-driven approval gate at `exec_tool_func`.
2. Support per-call approval state via a dedicated `ToolApprovalInstance` object.
3. Allow configurable timeout policies (`deny`, `allow`, `ask_again`).
4. Support fine-grained rules that inspect tool arguments (e.g. substring, exact match, regex, list membership).
5. Keep the change minimally invasive to the existing ReAct step loop (`StepCallTool.execute_step_action`).
6. Preserve backward compatibility: when approval is disabled, tool calls execute exactly as before.
7. Design the wait/notify layer as a replaceable transport so local CLI approval can later be replaced by network-based approval without changing `ToolApprovalInstance` or the decorator.

## Configuration Schema

Configuration is read at call time so rules can be updated without restarting the agent.

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TOPSAILAI_TOOL_APPROVAL_ENABLED` | `0` | Master switch. `1` enables the approval mechanism, `0` disables it. |
| `TOPSAILAI_TOOL_APPROVAL_RULES` | `${TOPSAILAI_WORK_FOLDER}/tool_approval.json` | JSON approval rules. Either a JSON array literal or a path to a file containing a JSON array. |
| `TOPSAILAI_TOOL_APPROVAL_DEFAULT_TIMEOUT` | `60` | Default timeout in seconds when a rule does not specify one. |
| `TOPSAILAI_TOOL_APPROVAL_DEFAULT_POLICY` | `deny` | Default timeout policy when a rule does not specify one. Must be one of `deny`, `allow`, `ask_again`. |

### JSON Rule Format

`TOPSAILAI_TOOL_APPROVAL_RULES` must be valid JSON. The top-level value is an array of rule objects. Rules are sorted by `priority` ascending (smaller values first) before evaluation; the first matching rule wins. If no rule matches, the call is allowed without approval.

#### Rule Object Schema

```json
{
  "name": "optional human-readable name",
  "match": "tool name pattern",
  "mode": "require | bypass",
  "params": [
    { "param": "arg_name", "op": "contains", "value": "substring" }
  ],
  "logic": "and | or",
  "timeout": 120,
  "policy": "deny | allow | ask_again",
  "priority": 10
}
```

Fields:

- `match` (required): Tool name pattern. Supports exact name, prefix (`cmd_*`), suffix (`*_write`), or wildcard (`*`). See `Match Pattern Syntax` below.
- `mode` (required): `require` means approval is needed; `bypass` means this rule explicitly bypasses approval. `skip` is accepted as a backward-compatible alias for `bypass`.
- `params` (optional): Array of parameter-level condition objects. See `Parameter Conditions` below.
- `logic` (optional): `and` or `or`. Controls how the conditions inside `params` are combined. Default is `and`. It does **not** affect the `match` requirement: the tool name must always match the rule pattern.
- `timeout` (optional): Approval wait timeout in seconds. Falls back to `TOPSAILAI_TOOL_APPROVAL_DEFAULT_TIMEOUT`.
- `policy` (optional): Timeout policy. Falls back to `TOPSAILAI_TOOL_APPROVAL_DEFAULT_POLICY`.
- `priority` (optional): Integer ordering hint. Default is `0`. **Smaller values are evaluated first**, so a rule with `priority: 1` takes precedence over a rule with `priority: 10` when both match. Rules with the same priority preserve their original array order.

#### Match Pattern Syntax

- Only the `*` wildcard is supported.
- `*` matches any character sequence, including an empty sequence.
- Matching is case-sensitive.
- `?` and other glob syntax are **not** supported.

Examples:

| Pattern | Matches | Does Not Match |
|---------|---------|----------------|
| `cmd_tool-exec_cmd` | `cmd_tool-exec_cmd` | `Cmd_tool-exec_cmd`, `cmd_tool-exec_cmd2` |
| `cmd_*` | `cmd_tool-exec_cmd`, `cmd_tool-read_file` | `Cmd_tool-exec_cmd` |
| `*_write` | `file_tool-write_file`, `file_tool-write_line` | `file_tool-read_file` |
| `*` | any tool name | — |

#### Parameter Conditions

Each condition object has the form:

```json
{ "param": "<arg_name>", "op": "<operator>", "value": "<value>" }
```

Supported operators:

| Operator | Description | Example |
|----------|-------------|---------|
| `contains` | Substring match (string only). | `{ "param": "cmd", "op": "contains", "value": "git reset" }` |
| `not_contains` | Substring must not be present. | `{ "param": "cmd", "op": "not_contains", "value": "sudo" }` |
| `eq` | Exact equality. | `{ "param": "file_path", "op": "eq", "value": "/etc/passwd" }` |
| `ne` | Not equal. | `{ "param": "role", "op": "ne", "value": "system" }` |
| `regex` | Regular expression match. | `{ "param": "cmd", "op": "regex", "value": "rm\\s+-rf\\s+/" }` |
| `in` | Value is in a comma-separated list. | `{ "param": "action", "op": "in", "value": "delete,write,exec" }` |
| `not_in` | Value is not in a comma-separated list. | `{ "param": "action", "op": "not_in", "value": "read" }` |
| `starts_with` | String starts with prefix. | `{ "param": "cmd", "op": "starts_with", "value": "git reset" }` |
| `ends_with` | String ends with suffix. | `{ "param": "file_path", "op": "ends_with", "value": ".env" }` |
| `gt` / `gte` / `lt` / `lte` | Numeric comparisons. | `{ "param": "timeout", "op": "gte", "value": 600 }` |
| `exists` | Parameter is present. | `{ "param": "force", "op": "exists" }` |

Multiple parameter conditions in the same `params` array are combined with AND by default. To use OR, set `"logic": "or"` on the rule. The `match` requirement is always evaluated first and independently; if the tool name does not match the rule pattern, the rule does not match regardless of `params`.

#### Rule Ordering

Rules are evaluated in ascending order of `priority` (smallest first). When two rules have the same `priority`, their relative order is the same as in the original JSON array. Because evaluation stops at the first match, placing a more specific rule at a smaller `priority` ensures it wins over a broader rule.

For example, a `bypass` rule with `match: "cmd_*"` and `priority: 10` will be overridden by a `require` rule with `match: "cmd_*"` and `priority: 1`, because the `require` rule is evaluated first.

### File Path Support

If the value of `TOPSAILAI_TOOL_APPROVAL_RULES` is a path to an existing file, the file content is read and parsed as JSON. Otherwise the value is parsed directly as JSON. This allows large rule sets to be maintained in separate files.

### Configuration Error Handling

The approval mechanism must fail safely. The recommended default behavior is:

| Error Condition | Behavior |
|-----------------|----------|
| `TOPSAILAI_TOOL_APPROVAL_ENABLED=0` | Approval is disabled; all tool calls execute normally. |
| `TOPSAILAI_TOOL_APPROVAL_RULES` points to a non-existent file or is empty/unset | Approval is effectively disabled; all tool calls execute normally. |
| JSON parsing fails | Log an error, disable approval for the current process, and allow tool calls to execute normally. |
| File path does not exist or is unreadable | Log an error, disable approval for the current process, and allow tool calls to execute normally. |
| Rule schema is invalid | Log a warning, skip the invalid rule, and continue evaluating remaining rules. |
| Unknown `mode` value | Treat as `require` (safe default) and log a warning. |
| Unknown `policy` value | Treat as `deny` (safe default) and log a warning. |
| Invalid `priority` value | Treat as `0` and log a warning. |

This fail-open behavior ensures that a misconfigured approval system does not block the agent entirely. In high-security environments, a future `TOPSAILAI_TOOL_APPROVAL_FAIL_CLOSED=1` option could be added to fail closed instead.

### Example Configuration

```bash
TOPSAILAI_TOOL_APPROVAL_ENABLED=1
TOPSAILAI_TOOL_APPROVAL_DEFAULT_TIMEOUT=120
TOPSAILAI_TOOL_APPROVAL_DEFAULT_POLICY=deny
TOPSAILAI_TOOL_APPROVAL_RULES='[
  {
    "name": "deny dangerous rm",
    "match": "cmd_tool-exec_cmd",
    "mode": "require",
    "params": [
      { "param": "cmd", "op": "regex", "value": "rm\\s.*\\s-rf?\\s.*\\s/\\s" }
    ],
    "timeout": 30,
    "policy": "deny",
    "priority": 1
  },
  {
    "name": "git reset approval",
    "match": "cmd_tool-exec_cmd",
    "mode": "require",
    "params": [
      { "param": "cmd", "op": "contains", "value": "git reset" }
    ],
    "timeout": 300,
    "policy": "deny",
    "priority": 10
  },
  {
    "name": "write file approval",
    "match": "file_tool-write_file",
    "mode": "require",
    "timeout": 60,
    "policy": "ask_again",
    "priority": 20
  },
  {
    "name": "bypass read-only file tools",
    "match": "file_tool-read_*",
    "mode": "bypass",
    "priority": 30
  },
  {
    "name": "catch-all approval",
    "match": "*",
    "mode": "require",
    "timeout": 30,
    "policy": "deny",
    "priority": 100
  }
]'
```

In this example:

1. Any `cmd_tool-exec_cmd` whose `cmd` contains `rm -rf` requires approval and is denied on timeout (evaluated first because of the smallest `priority`).
2. Any `cmd_tool-exec_cmd` whose `cmd` contains `git reset` requires approval, times out after 300 seconds, and is denied on timeout.
3. Any `file_tool-write_file` requires approval, times out after 60 seconds, and asks once more on timeout.
4. Any `file_tool-read_*` bypasses approval.
5. All other tools require approval and are denied on timeout.

#### Priority Example

The following snippet shows how `priority` changes the effective rule even when the broader rule appears first in the array:

```json
[
  {
    "name": "bypass all commands",
    "match": "cmd_*",
    "mode": "bypass",
    "priority": 100
  },
  {
    "name": "require git reset",
    "match": "cmd_*",
    "mode": "require",
    "params": [
      { "param": "cmd", "op": "contains", "value": "git reset" }
    ],
    "priority": 1
  }
]
```

Because the `require` rule has a smaller `priority` (`1` vs `100`), it is evaluated first. A `cmd_tool-exec_cmd` call whose `cmd` contains `git reset` therefore requires approval, even though the `bypass all commands` rule also matches and appears earlier in the array.

## ApprovalTransport Abstraction

The `ask` / `await` logic must not be hard-coded to a local `threading.Event`. Instead, `ToolApprovalInstance` delegates all request delivery, response waiting, and wake-up signaling to a pluggable `ApprovalTransport`. This lets the same approval code work in local CLI mode today and in network-based mode tomorrow.

### Transport Interface

```python
from abc import ABC, abstractmethod


class ApprovalTransport(ABC):
    """
    Abstraction for sending an approval request to a human operator and
    waiting for a response. Implementations may be local (CLI prompt) or
    remote (HTTP/WebSocket/message queue).
    """

    @abstractmethod
    def send_request(self, instance: "ToolApprovalInstance") -> None:
        """
        Notify the operator that an approval decision is needed.
        This method must be non-blocking; the actual wait happens in
        wait_response().
        """
        ...

    @abstractmethod
    def wait_response(
        self,
        instance: "ToolApprovalInstance",
        timeout: float | None = None,
    ) -> str:
        """
        Block until the instance is approved, denied, or the timeout expires.
        Returns one of ToolApprovalInstance.STATUS_* values.
        """
        ...

    @abstractmethod
    def on_resolved(self, instance: "ToolApprovalInstance") -> None:
        """
        Called by ToolApprovalInstance.approve() / deny() to wake up the
        waiter in wait_response(). The transport decides how to wake its
        own wait mechanism.
        """
        ...

    @abstractmethod
    def supports_external_resolution(self) -> bool:
        """
        Return True if this transport allows an external system to call
        instance.approve()/deny() while wait_response() is in progress.
        Local transports typically return False; network transports return True.
        """
        ...
```

### Local Synchronous Transport

The default transport for the current implementation uses a `threading.Event` and a local input prompt.

```python
import threading


class LocalApprovalTransport(ApprovalTransport):
    """
    Default local transport. Sends the request by printing to stdout and
    waits for the user to type approve/deny in the same process.
    """

    def __init__(self):
        self._events: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def send_request(self, instance: "ToolApprovalInstance") -> None:
        with self._lock:
            self._events[instance.id] = threading.Event()
        print(
            f"[APPROVAL REQUEST] {instance.id}\n"
            f"  Tool: {instance.tool_name}\n"
            f"  Args: {instance.tool_args}\n"
            f"  Timeout: {instance.timeout}s\n"
            "  Type 'approve' or 'deny': "
        )
        # In a real implementation this would spawn a short input reader
        # thread that calls instance.approve() / deny() when the user types.

    def wait_response(
        self,
        instance: "ToolApprovalInstance",
        timeout: float | None = None,
    ) -> str:
        with self._lock:
            event = self._events.get(instance.id)
        if event is None:
            return instance.status
        if event.wait(timeout=timeout if timeout is not None else instance.timeout):
            return instance.status
        instance.mark_timeout()
        return instance.STATUS_TIMEOUT

    def on_resolved(self, instance: "ToolApprovalInstance") -> None:
        with self._lock:
            event = self._events.pop(instance.id, None)
        if event is not None:
            event.set()

    def supports_external_resolution(self) -> bool:
        return False
```

### Network Transport (Reserved Extension Point)

A network transport sends the approval request over HTTP/WebSocket/a message queue and waits for an external system to resolve the instance. The example below uses a callback registry plus a `threading.Condition` so the transport does not rely on `threading.Event`.

```python
import threading


class NetworkApprovalTransport(ApprovalTransport):
    """
    Reserved network transport. Sends approval requests to a remote approval
    service and waits for a callback. Not fully implemented here; this class
    documents the extension points.
    """

    def __init__(self, endpoint: str, auth_token: str | None = None):
        self.endpoint = endpoint
        self.auth_token = auth_token
        self._conditions: dict[str, threading.Condition] = {}
        self._lock = threading.Lock()

    def send_request(self, instance: "ToolApprovalInstance") -> None:
        with self._lock:
            self._conditions[instance.id] = threading.Condition()
        payload = {
            "id": instance.id,
            "tool_name": instance.tool_name,
            "tool_args": instance.tool_args,
            "context": instance.context,
            "timeout": instance.timeout,
            "callback_url": f"{self.endpoint}/resolve/{instance.id}",
        }
        # POST payload to the approval service.
        # The service is responsible for notifying a human operator.
        post_json(f"{self.endpoint}/requests", payload, headers=self._headers())

    def wait_response(
        self,
        instance: "ToolApprovalInstance",
        timeout: float | None = None,
    ) -> str:
        with self._lock:
            condition = self._conditions.get(instance.id)
        if condition is None:
            return instance.status
        with condition:
            if condition.wait(timeout=timeout if timeout is not None else instance.timeout):
                return instance.status
        instance.mark_timeout()
        return instance.STATUS_TIMEOUT

    def on_resolved(self, instance: "ToolApprovalInstance") -> None:
        with self._lock:
            condition = self._conditions.pop(instance.id, None)
        if condition is not None:
            with condition:
                condition.notify_all()

    def supports_external_resolution(self) -> bool:
        return True

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        return headers
```

External systems resolve a network instance by calling:

```python
# REST endpoint example
@app.post("/resolve/{instance_id}")
def resolve_approval(instance_id: str, decision: str):
    instance = get_pending_instance(instance_id)
    if decision == "approve":
        instance.approve(by="remote_user")
    elif decision == "deny":
        instance.deny(by="remote_user")
    else:
        raise ValueError(f"Unknown decision: {decision}")
```

The call chain is:

1. External system calls `instance.approve(by="remote_user")` or `instance.deny(by="remote_user")`.
2. `ToolApprovalInstance` updates its status and calls `self.transport.on_resolved(self)`.
3. The transport wakes up `wait_response()`.
4. The decorator receives the resolved status and proceeds or raises `ToolApprovalDeniedError`.

### Transport Selection

- `ToolApprovalInstance` receives its transport via constructor injection.
- The default transport is `LocalApprovalTransport()`.
- A future environment variable (e.g. `TOPSAILAI_TOOL_APPROVAL_TRANSPORT`) can select a different transport class without changing `ToolApprovalInstance` or the decorator.

## ToolApprovalInstance Design

### Class Responsibilities

`ToolApprovalInstance` represents the approval evaluation and state for a single tool call. The approval decorator creates an instance for every call and asks it for a decision. All outcomes — no approval needed, allow, deny, or ask — are handled inside the instance.

The instance is intentionally decoupled from transport details: it stores approval state and exposes `approve()` / `deny()` / `wait_for_decision()`, while the actual notification, blocking, and wake-up are delegated to the injected `ApprovalTransport`.

### Decision States

```python
class ApprovalDecision:
    NO_APPROVAL = "no_approval"   # no rule matched, execute original logic
    ALLOW = "allow"               # rule says allow, execute original logic
    DENY = "deny"                 # rule says deny, raise ToolApprovalDeniedError
    ASK = "ask"                   # rule says require approval, wait for human decision
```

### Interface

```python
class ToolApprovalInstance:
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_DENIED = "denied"
    STATUS_TIMEOUT = "timeout"

    def __init__(
        self,
        tool_name: str,
        tool_args: dict,
        context: dict | None = None,
        transport: ApprovalTransport | None = None,
    ):
        self.id = generate_uuid()           # unique per call
        self.tool_name = tool_name
        self.tool_args = tool_args
        self.context = context or {}        # e.g. session_id, agent_name, step index
        self.transport = transport or get_default_approval_transport()
        self.status = self.STATUS_PENDING
        self.decision_by = None             # user / policy / system / remote_user
        self.decision_at = None             # timestamp
        self.created_at = now()
        self.timeout = default_timeout()
        self.policy = default_policy()

    def decide(self) -> ApprovalDecision:
        """
        Evaluate configured rules against this tool call.
        Returns an ApprovalDecision describing what the caller should do.
        """
        if not is_tool_approval_enabled():
            return ApprovalDecision(action=ApprovalDecision.NO_APPROVAL)

        rule = match_approval_rule(tool_name=self.tool_name, tool_args=self.tool_args)
        if not rule:
            return ApprovalDecision(action=ApprovalDecision.NO_APPROVAL)

        if rule.mode in ("bypass", "skip"):
            return ApprovalDecision(action=ApprovalDecision.ALLOW, rule=rule)

        if rule.mode == "require":
            self.timeout = rule.timeout or self.timeout
            self.policy = rule.policy or self.policy
            return ApprovalDecision(
                action=ApprovalDecision.ASK,
                rule=rule,
                timeout=self.timeout,
                policy=self.policy,
            )

        # Unknown mode defaults to require (safe default).
        return ApprovalDecision(action=ApprovalDecision.ASK, rule=rule)

    def approve(self, by: str = "user"):
        """External caller confirms approval."""
        self.status = self.STATUS_APPROVED
        self.decision_by = by
        self.decision_at = now()
        self.transport.on_resolved(self)

    def deny(self, by: str = "user"):
        """External caller denies approval."""
        self.status = self.STATUS_DENIED
        self.decision_by = by
        self.decision_at = now()
        self.transport.on_resolved(self)

    def mark_timeout(self):
        """Called by transports to record a timeout."""
        self.status = self.STATUS_TIMEOUT
        self.decision_by = "policy"
        self.decision_at = now()

    def apply_timeout_policy(self, policy: str) -> str:
        """
        Resolve a timeout according to the rule's policy.
        Returns the resolved status.
        """
        if policy == "allow":
            self.status = self.STATUS_APPROVED
            self.decision_by = "policy"
            self.decision_at = now()
            return self.status
        if policy == "ask_again":
            # Reset state and allow one additional wait cycle.
            self.status = self.STATUS_PENDING
            self.decision_by = None
            self.decision_at = None
            return self.status
        # "deny" and unknown policies default to deny.
        self.status = self.STATUS_DENIED
        self.decision_by = "policy"
        self.decision_at = now()
        return self.status

    def wait_for_decision(self, timeout: float, policy: str) -> str:
        """
        Wait for a human decision, applying timeout policy and ask_again logic.
        Returns the final status. This method encapsulates all approval waiting
        logic so the decorator does not need to know about ask_again cycles.
        """
        status = self.transport.wait_response(self, timeout=timeout)
        if status != self.STATUS_TIMEOUT:
            return status

        status = self.apply_timeout_policy(policy)
        if status == self.STATUS_PENDING:
            # ask_again: one extra wait cycle, then deny if still no answer.
            status = self.transport.wait_response(self, timeout=timeout)
            if status == self.STATUS_TIMEOUT:
                status = self.apply_timeout_policy("deny")
        return status
```

### Persistence and Notification (Future)

- The instance can be serialized to a shared store (e.g. SQLite via `context/chat_history_manager/sql.py`) so a separate UI process can list pending approvals.
- A lightweight notification hook (`TOPSAILAI_TOOL_APPROVAL_NOTIFICATION_HOOK`) can be invoked on instance creation.
- In network mode, `send_request()` is the notification; no extra hook is required.

## Decorator Integration

The approval gate is implemented as a decorator so the body of `exec_tool_func` does not need to change.

### ToolApprovalDeniedError

`ToolApprovalDeniedError` inherits from `ToolApprovalException` (which extends the base `Exception` class). It is raised by the approval decorator when a tool call is denied by the approval policy or when approval times out.

```python
class ToolApprovalException(Exception):
    """ Base Exception """
    pass

class ToolApprovalDeniedError(ToolApprovalException):
    """
    Raised when a tool call is denied by the approval policy.
    """

    def __init__(self, message: str, instance_id: str | None = None):
        super().__init__(message)
        self.instance_id = instance_id
```

### Decorator Design

```python
import functools


def with_tool_approval(wrapped):
    """
    Decorator that wraps a tool execution function with the approval gate.
    The wrapped function is called with the same arguments when approval is
    granted or not required.
    """
    @functools.wraps(wrapped)
    def wrapper(tool_func, args, tool_name=None):
        effective_tool_name = tool_name or getattr(tool_func, "__name__", "unknown")

        instance = ToolApprovalInstance(
            tool_name=effective_tool_name,
            tool_args=args,
            context=build_approval_context(),
            transport=get_default_approval_transport(),
        )
        decision = instance.decide()

        if decision.action in (ApprovalDecision.NO_APPROVAL, ApprovalDecision.ALLOW):
            # No approval required or explicitly allowed: run original logic.
            return wrapped(tool_func, args, tool_name=tool_name)

        if decision.action == ApprovalDecision.DENY:
            raise ToolApprovalDeniedError(
                f"Tool [{effective_tool_name}] denied by approval policy"
            )

        # decision.action == ApprovalDecision.ASK
        register_pending_approval(instance)
        try:
            instance.transport.send_request(instance)
            notify_approval_requested(instance)

            status = instance.wait_for_decision(
                timeout=decision.timeout,
                policy=decision.policy,
            )

            if status in (ToolApprovalInstance.STATUS_DENIED, ToolApprovalInstance.STATUS_TIMEOUT):
                raise ToolApprovalDeniedError(
                    f"Tool [{effective_tool_name}] denied: approval {status}"
                )
        finally:
            unregister_pending_approval(instance.id)

        # STATUS_APPROVED
        return wrapped(tool_func, args, tool_name=tool_name)

    return wrapper
```

### exec_tool_func Integration

`exec_tool_func` itself is unchanged; only the decorator is added at definition time:

```python
@with_tool_approval
def exec_tool_func(tool_func, args, tool_name=None):
    if not tool_name:
        tool_name = tool_func.__name__

    # existing exec_tool_func body continues unchanged
    ...
```

### Notes on Integration

- `StepCallTool.execute_step_action()` does not need to change; it continues to call `exec_tool_func(tool_func, args, tool_name=tool)`.
- `match_approval_rule` evaluates both the tool-name pattern and the parameter conditions defined by the matched rule.
- If approval is denied, the decorator raises `ToolApprovalDeniedError`. The step loop in `ai_base/agent_types/tool.py` explicitly catches `ToolApprovalDeniedError` so the agent can surface the denial as an observation.
## Concurrency Safety

The pending-approval registry is a process-wide shared resource. It must be thread-safe:

- Use a `threading.Lock` or `threading.RLock` around `register_pending_approval()` / `unregister_pending_approval()` / `get_pending_instance()`.
- Alternatively, store pending instances in a thread-safe structure such as `queue.SimpleQueue` plus a lock-protected lookup dict.
- Network transports may receive callbacks on a different thread than the one running `wait_response()`. The transport's wake-up mechanism (e.g. `Condition.notify_all()`) must be thread-safe.
- `ToolApprovalInstance.approve()` / `deny()` are designed to be callable from any thread; they update status and delegate wake-up to the transport.

## Timeout Policy Behavior

| Policy | On Timeout | Result |
|--------|-----------|--------|
| `deny` | Reject the tool call. | `ToolApprovalDeniedError` is raised. |
| `allow` | Auto-approve and execute the original tool. | Tool runs normally. |
| `ask_again` | Reset the instance to `pending` and allow one additional wait cycle. | If still no decision, falls back to `deny`. |

## Example Usage / Flow

### Scenario: `git reset` command approval

1. Agent decides to call `cmd_tool-exec_cmd` with `{"cmd": "git reset --hard HEAD~1"}`.
2. `StepCallTool.execute_step_action` calls `exec_tool_func(exec_cmd_func, args, tool_name="cmd_tool-exec_cmd")`.
3. The decorator creates a `ToolApprovalInstance` and calls `decide()`.
4. Rule `git reset approval` matches (`cmd` contains `git reset`), so the decision is `ASK` with `timeout=300` and `policy=deny`.
5. The instance is registered and `transport.send_request(instance)` notifies the operator.
6. The human clicks **Approve**; `instance.approve()` sets status to `approved`.
7. The decorator proceeds to call the original `exec_tool_func`, which executes `cmd_tool-exec_cmd` normally.

If no human response arrives within 300 seconds:

1. `instance.wait_for_decision()` returns `denied` after applying the timeout policy.
2. The decorator raises `ToolApprovalDeniedError`.
3. The agent receives the denial as the observation.

### Scenario: Write-file approval

1. Agent decides to call `file_tool-write_file` with `{"file_path": "/etc/hosts", "content": "..."}`.
2. The decorator creates a `ToolApprovalInstance`; rule `write file approval` matches, decision is `ASK` with `timeout=60` and `policy=ask_again`.
3. A human operator sees the pending approval and clicks **Deny**.
4. `instance.deny()` sets status to `denied`.
5. The decorator raises `ToolApprovalDeniedError`.
6. The agent receives the denial and reports it as the observation.

If the human does not respond within 60 seconds:

1. `instance.wait_for_decision()` applies `ask_again` and waits another 60 seconds.
2. If there is still no response, it applies `deny` and raises `ToolApprovalDeniedError`.

## Testing Strategy

### Unit Tests

1. **Rule matcher**: Test exact, prefix, suffix, and wildcard `match` patterns; case sensitivity; first-match-wins semantics; and `priority` ordering (smaller values evaluated first).
2. **Parameter conditions**: Test each operator (`contains`, `eq`, `regex`, `in`, etc.) and the `logic: or` combination.
3. **ApprovalDecision**: Test `decide()` outcomes for disabled approval, no match, bypass, require, and unknown mode.
4. **Timeout policies**: Test `apply_timeout_policy()` for `deny`, `allow`, and `ask_again`.

### Integration Tests

1. **Decorator with mock transport**: Create a `MockApprovalTransport` that records `send_request` calls and can be resolved manually. Verify that:
   - No-approval calls execute the wrapped function directly.
   - Bypass rules execute the wrapped function directly.
   - Require rules block until resolved.
   - Deny rules raise `ToolApprovalDeniedError` without calling the wrapped function.
   - Timeout with `ask_again` performs exactly one extra wait cycle.

2. **Decorator with `exec_tool_func`**: Wrap a minimal `exec_tool_func` stand-in and verify the full flow including tool-name extraction.

### Transport Tests

1. **LocalApprovalTransport**: Verify `send_request`, `wait_response`, `on_resolved`, and timeout behavior using real `threading.Event` objects.
2. **NetworkApprovalTransport mock**: Verify that an external callback can resolve an instance and wake `wait_response()`.

### End-to-End Tests

1. Set `TOPSAILAI_TOOL_APPROVAL_RULES` via environment variable and call the decorated `exec_tool_func`.
2. Verify file-path loading works and JSON parsing errors fall back to disabled approval.
3. Verify `ToolApprovalDeniedError` is raised and propagated correctly.

## Open Questions / Future Extensions

1. **Transport Selection**: Add `TOPSAILAI_TOOL_APPROVAL_TRANSPORT` to choose between `local`, `http`, `websocket`, or custom transport classes.
2. **Network Callback Security**: How are callback endpoints authenticated? Should instance IDs be signed or short-lived?
3. **UI/Transport**: How are pending approvals surfaced? Options: CLI prompt, web dashboard, file-based queue, or a dedicated `approval_tool`.
4. **Batch Approval**: Should multiple pending approvals be groupable into a single decision?
5. **Audit Log**: Should every approval instance be persisted for security review?
6. **Role-Based Rules**: Should rules support user roles or agent names in addition to tool name patterns?
7. **Pre-Approval Cache**: Should recently approved identical calls be auto-approved for a short TTL?
8. **Async Mode**: Should `exec_tool_func` support non-blocking approval so the agent can do other work while waiting?
9. **Nested Parameter Matching**: Should rules support matching inside nested dict/list arguments (e.g. `args.cmd[0]`)?
10. **Fail-Closed Mode**: Should `TOPSAILAI_TOOL_APPROVAL_FAIL_CLOSED=1` be supported for high-security environments?
