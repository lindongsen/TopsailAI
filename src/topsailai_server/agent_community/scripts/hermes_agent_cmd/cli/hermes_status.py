#!/usr/bin/env python3
"""
Hermes Agent Session Status Check Tool
Returns status: idle | processing | not_found | error

Usage:
  ./hermes_status.py <session_id>
  HERMES_SESSION_ID=<session_id> ./hermes_status.py
  Returns JSON to stdout + human-readable status to stderr
"""
import json, os, sys, time, urllib.request

DEFAULT_BASE_URL = "http://127.0.0.1:8642"
PROCESSING_TIMEOUT = 120  # If no response exceeds this time, treat as idle (likely timed out)


def _read_env_file(path="") -> dict:
    if not path:
        path = os.path.join(os.path.expanduser("~"), ".hermes", ".env")
    result = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                result[k.strip()] = v.strip()
    except FileNotFoundError:
        pass
    return result


def _env(key: str, default="") -> str:
    val = os.environ.get(key, "").strip()
    if val:
        return val
    cache = getattr(_env, "_cache", None)
    if cache is None:
        cache = _read_env_file()
        _env._cache = cache
    return cache.get(key, default).strip()


def _call(method, path, body=None):
    base = _env("HERMES_API_BASE", DEFAULT_BASE_URL).rstrip("/")
    key = _env("HERMES_API_KEY")
    if not key:
        env = _read_env_file()
        key = env.get("API_SERVER_KEY", "")
        if not key:
            return 0, {"error": "API key not found"}

    url = f"{base}{path}"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {"error": str(e)}
    except Exception as e:
        return 0, {"error": str(e)}


def get_global_active_agents() -> int:
    status, data = _call("GET", "/health/detailed")
    if status == 200:
        return data.get("active_agents", 0)
    status, data = _call("GET", "/health")
    if status == 200:
        return data.get("active_agents", 0)
    return 0


def check_session_status(session_id: str) -> dict:
    """Check session status. Returns a dict with status details."""
    result = {
        "session_id": session_id,
        "status": "unknown",
        "reason": "",
        "last_message_role": None,
        "last_message_age_seconds": None,
        "message_count": 0,
        "active_agents_global": 0,
        "ended": False,
    }

    # 1. Get session detail
    status, data = _call("GET", f"/api/sessions/{session_id}")
    if status == 404:
        result["status"] = "not_found"
        result["reason"] = "Session does not exist or was pruned"
        return result
    if status != 200:
        result["status"] = "error"
        result["reason"] = f"HTTP {status}: {data}"
        return result

    s = data.get("session", {})
    result["message_count"] = s.get("message_count", 0)
    result["ended"] = bool(s.get("ended_at"))

    # 2. Get messages
    msg_status, msg_data = _call("GET", f"/api/sessions/{session_id}/messages")
    msgs = msg_data.get("data", []) if msg_status == 200 else []
    # Fallback to top-level messages key
    if not msgs and isinstance(msg_data, dict) and "messages" in msg_data:
        msgs = msg_data["messages"]

    if not msgs:
        # Empty session
        if result["ended"]:
            result["status"] = "idle"
            result["reason"] = "Empty and ended session"
        else:
            result["status"] = "idle"
            result["reason"] = "Empty session, no pending work"
        return result

    last = msgs[-1]
    result["last_message_role"] = last.get("role")
    last_ts = last.get("timestamp", 0) or 0
    age = time.time() - last_ts if last_ts else None
    result["last_message_age_seconds"] = round(age, 1) if age is not None else None

    # 3. Check global active agents
    active = get_global_active_agents()
    result["active_agents_global"] = active

    # 4. Determine status

    # If session is ended, it's idle
    if result["ended"]:
        result["status"] = "idle"
        result["reason"] = "Session has been ended"
        return result

    # If last message is from assistant, session is idle
    if last.get("role") == "assistant":
        result["status"] = "idle"
        result["reason"] = "Last message is assistant reply"
        return result

    # If last message is from user
    if last.get("role") == "user":
        if age is None:
            # No timestamp, can't determine age
            result["status"] = "processing"
            result["reason"] = "Last message is from user, no timestamp available"
            return result

        if age < 10:
            # Very recent, likely still processing
            result["status"] = "processing"
            result["reason"] = f"User message sent {age:.1f}s ago"
            return result

        if age > PROCESSING_TIMEOUT:
            # Stuck too long, assume idle (timeout/failure)
            result["status"] = "idle"
            result["reason"] = f"User message sent {age:.1f}s ago (> {PROCESSING_TIMEOUT}s timeout)"
            return result

        # In the middle zone: check global active agents
        if active > 0:
            result["status"] = "processing"
            result["reason"] = f"User message sent {age:.1f}s ago, {active} global agent(s) running"
        else:
            result["status"] = "idle"
            result["reason"] = f"User message sent {age:.1f}s ago, but no agents currently active (may have timed out)"
        return result

    # Unknown role
    result["status"] = "idle"
    result["reason"] = f"Unknown last message role: {last.get('role')}"
    return result


def main():
    session_id = ""
    if len(sys.argv) >= 2:
        session_id = sys.argv[1].strip()
    else:
        session_id = os.environ.get("HERMES_SESSION_ID", "").strip()

    if not session_id:
        print("Usage: hermes_status.py <session_id>", file=sys.stderr)
        print("   or: HERMES_SESSION_ID=<session_id> hermes_status.py", file=sys.stderr)
        print("\nReturns JSON to stdout:", file=sys.stderr)
        print('  {"session_id":"...","status":"idle|processing|not_found|error",...}', file=sys.stderr)
        sys.exit(1)

    result = check_session_status(session_id)

    # Human-readable to stderr
    status = result["status"]
    reason = result["reason"]
    role = result["last_message_role"]
    age = result["last_message_age_seconds"]
    msgs = result["message_count"]
    active = result["active_agents_global"]

    if status == "not_found":
        print(f"[NOT FOUND] {session_id}", file=sys.stderr)
    elif status == "error":
        print(f"[ERROR] {session_id}: {reason}", file=sys.stderr)
    else:
        status_icon = "RUN" if status == "processing" else "OK"
        age_str = f"{age:.1f}s old" if age is not None else "N/A"
        print(
            f"[{status_icon}] {session_id} | status={status} | msgs={msgs} | "
            f"last={role} | age={age_str} | agents={active}",
            file=sys.stderr,
        )
        if reason:
            print(f"  reason: {reason}", file=sys.stderr)

    # Machine-readable JSON to stdout
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
