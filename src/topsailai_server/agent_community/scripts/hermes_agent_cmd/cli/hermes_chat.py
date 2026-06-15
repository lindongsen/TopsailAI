#!/usr/bin/env python3
"""
Hermes Agent Native Session Chat Client
Usage:
  HERMES_API_KEY=xxx HERMES_API_BASE=http://127.0.0.1:8642 ./scripts/hermes_chat.py "Hello"
  HERMES_API_KEY=xxx ./scripts/hermes_chat.py -s abc123 "Continue chatting"
  HERMES_API_KEY=xxx ./scripts/hermes_chat.py --create Create session only
  HERMES_SESSION_ID=abc123 HERMES_USER_MESSAGE="Hello" ./scripts/hermes_chat.py
  HERMES_SESSION_ID=abc123 HERMES_USER_MESSAGE="Hello" HERMES_SYSTEM_PROMPT="Be helpful" ./scripts/hermes_chat.py
"""
import argparse
import json
import os
import sys
import urllib.request
import urllib.error


DEFAULT_BASE_URL = "http://127.0.0.1:8642"
DEFAULT_TIMEOUT = 600
MIN_TIMEOUT = 300


def _get_timeout() -> int:
    """Return HTTP timeout in seconds. Default 600, env HERMES_AGENT_TIMEOUT overrides, min 300."""
    try:
        timeout = int(os.environ.get("HERMES_AGENT_TIMEOUT", str(DEFAULT_TIMEOUT)).strip())
    except (ValueError, TypeError):
        timeout = DEFAULT_TIMEOUT
    if timeout < MIN_TIMEOUT:
        timeout = MIN_TIMEOUT
    return timeout


def _api(method: str, path: str, body=None, headers=None):
    base = os.environ.get("HERMES_API_BASE", DEFAULT_BASE_URL).strip().rstrip("/")
    key = os.environ.get("HERMES_API_KEY", "").strip()
    if not key:
        print("ERROR: HERMES_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    url = f"{base}{path}"
    req_headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)

    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")

    req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=_get_timeout()) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8")), dict(resp.headers)
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8")
        try:
            return e.code, json.loads(body_text), {}
        except json.JSONDecodeError:
            return e.code, {"error": body_text}, {}
    except Exception as e:
        return 0, {"error": str(e)}, {}


def create_session(title: str = "") -> str:
    body = {}
    if title:
        body["title"] = title
    else:
        import datetime
        body["title"] = "chat_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    status, resp, _ = _api("POST", "/api/sessions", body=body)
    if status == 201:
        sid = resp.get("session", {}).get("id")
        print(f"[Session created] {sid}")
        return sid
    print(f"[Create session failed] {status}: {json.dumps(resp, ensure_ascii=False)}", file=sys.stderr)
    sys.exit(1)


def check_session(session_id: str) -> bool:
    status, resp, _ = _api("GET", f"/api/sessions/{session_id}")
    return status == 200


def send_message(session_id: str, message: str, system_message: str = "", stream: bool = False):
    body = {"message": message}
    if system_message:
        body["system_message"] = system_message

    if stream:
        # SSE streaming -- handling SSE with pure stdlib is troublesome, return non-streaming here
        # For SSE, recommended to use curl or requests
        print("[WARN] stream=True: recommended to use curl to directly call /chat/stream", file=sys.stderr)

    status, resp, hdrs = _api("POST", f"/api/sessions/{session_id}/chat", body=body)
    if status == 200:
        content = resp.get("message", {}).get("content", "")
        sid = resp.get("session_id", session_id)
        print(content)
        return sid
    print(f"[Chat failed] {status}: {json.dumps(resp, ensure_ascii=False)}", file=sys.stderr)
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Hermes Agent Session Chat")
    parser.add_argument("message", nargs="?", help="Message to send")
    parser.add_argument("-s", "--session", default="", help="Session ID (auto-create if not provided)")
    parser.add_argument("--create", action="store_true", help="Only create session, do not send message")
    parser.add_argument("--title", default="", help="New session title")
    parser.add_argument("--system", default="", help="system message / instructions")
    parser.add_argument("--stream", action="store_true", help="Enable streaming (pure stdlib SSE not yet supported)")
    args = parser.parse_args()

    if args.create:
        sid = create_session(args.title)
        print(sid)
        return

    # Resolve inputs with priority: CLI argument > environment variable
    session_id = (args.session or "").strip()
    if not session_id:
        session_id = os.environ.get("HERMES_SESSION_ID", "").strip()

    message = (args.message or "").strip()
    if not message:
        message = os.environ.get("HERMES_USER_MESSAGE", "").strip()

    system_message = (args.system or "").strip()
    if not system_message:
        system_message = os.environ.get("HERMES_SYSTEM_PROMPT", "").strip()

    if not message:
        parser.print_help()
        sys.exit(1)

    debug = os.environ.get("DEBUG", 0) in ["1", 1]

    if not session_id:
        session_id = create_session(args.title)
    else:
        exists = check_session(session_id)
        if not exists:
            if debug:
                print(f"[Session '{session_id}' not found, auto-creating...]")
            session_id = create_session(args.title)
        else:
            if debug:
                print(f"[Session resumed] {session_id}")

    send_message(session_id, message, system_message, args.stream)


if __name__ == "__main__":
    main()
