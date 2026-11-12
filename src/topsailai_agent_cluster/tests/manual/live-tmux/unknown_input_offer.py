#!/usr/bin/env python3
"""Drive the session-scope unknown-input send offer through the real CLI in tmux."""

import argparse
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from start_services import available_port, generate_certificates  # noqa: E402

PROMPT_PATTERN = re.compile(
    r"(?:workspace|endpoint\[[^\]]+\]|session\[[^\]]+\]|start\.[a-z]+|answer)>[^\n]*$"
)


def capture(target: str) -> str:
    """Capture the complete visible pane plus retained history."""
    return subprocess.run(
        ["tmux", "capture-pane", "-pJ", "-S", "-", "-t", target],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout


def wait_prompt(target: str, before: str, timeout: float) -> str:
    """Wait until the pane renders a new bottom prompt and return the new output."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(0.15)
        after = capture(target)
        if after == before:
            continue
        lines = [line for line in after.splitlines() if line.strip()]
        if lines and PROMPT_PATTERN.search(lines[-1]):
            return after
    raise RuntimeError("prompt did not return within the timeout")


def send_line(target: str, text: str, timeout: float) -> str:
    """Send one line and return the newly rendered terminal output."""
    before = capture(target)
    subprocess.run(["tmux", "send-keys", "-t", target, "-l", text], check=True)
    subprocess.run(["tmux", "send-keys", "-t", target, "Enter"], check=True)
    after = wait_prompt(target, before, timeout)
    common = 0
    for left, right in zip(before, after):
        if left != right:
            break
        common += 1
    return after[common:]


def start_services(runtime: Path, bin_dir: Path, provider: Path, project: Path) -> tuple[list[subprocess.Popen], int, str]:
    """Start one isolated Server and Endpoint backed by the fixture adapter."""
    runtime.mkdir(parents=True, exist_ok=True)
    project.mkdir(parents=True, exist_ok=True)
    generate_certificates(runtime)
    certs = runtime / "cert"
    api_port = available_port()
    channel_port = available_port()
    token = "live-offer-token"
    base = os.environ.copy()
    for key in list(base):
        if key.startswith(("AGENT_CLUSTER_", "TOPSAILAI_SESSION", "TOPSAILAI_TASK", "TOPSAILAI_CONTEXT_", "TOPSAILAI_USER_MESSAGE")):
            base.pop(key)
    base["AGENT_CLUSTER_TLS_CA_FILE"] = str(certs / "ca.pem")
    server_env = base | {
        "AGENT_CLUSTER_SERVER_API_LISTEN_ADDR": f"127.0.0.1:{api_port}",
        "AGENT_CLUSTER_SERVER_CHANNEL_LISTEN_ADDR": f"127.0.0.1:{channel_port}",
        "AGENT_CLUSTER_DATABASE_PATH": str(runtime / "server.db"),
        "AGENT_CLUSTER_SERVER_AUTH_TOKEN": token,
        "AGENT_CLUSTER_TLS_CERTIFICATE_FILE": str(certs / "server.pem"),
        "AGENT_CLUSTER_TLS_KEY_FILE": str(certs / "server.key"),
    }
    adapters = [{"adapter_id": "fixture-main", "provider_type": "fixture", "command": str(provider), "args": ["--mode", "one"], "timeout_ms": 5000}]
    endpoint_env = base | {
        "AGENT_CLUSTER_ENDPOINT_CHANNEL_ADDRESS": f"wss://127.0.0.1:{channel_port}",
        "AGENT_CLUSTER_ENDPOINT_ID": "live-tmux-endpoint",
        "AGENT_CLUSTER_DATABASE_PATH": str(runtime / "endpoint.db"),
        "AGENT_CLUSTER_TLS_CERTIFICATE_FILE": str(certs / "client.pem"),
        "AGENT_CLUSTER_TLS_KEY_FILE": str(certs / "client.key"),
        "AGENT_CLUSTER_ENDPOINT_ADAPTERS": json.dumps(adapters),
    }
    children: list[subprocess.Popen] = []
    for name, executable, environment in (
        ("server", bin_dir / "agent-cluster-server", server_env),
        ("endpoint", bin_dir / "agent-cluster-endpoint", endpoint_env),
    ):
        log = (runtime / f"{name}.log").open("wb")
        children.append(subprocess.Popen([str(executable)], cwd=runtime, env=environment, stdout=log, stderr=log))
        log.close()
        time.sleep(1)
        if children[-1].poll() is not None:
            raise RuntimeError(f"{name} exited during startup with {children[-1].returncode}")
    cli_environment = bin_dir / ".env.local"
    cli_environment.write_text(f"AGENT_CLUSTER_SERVER_URL=http://127.0.0.1:{api_port}\nAGENT_CLUSTER_TOKEN={token}\n", encoding="utf-8")
    cli_environment.chmod(0o600)
    return children, api_port, token


def wait_inventory(api_port: int, token: str, timeout: float) -> str:
    """Wait until the Server holds a fresh inventory containing the fixture session."""
    deadline = time.monotonic() + timeout
    url = f"http://127.0.0.1:{api_port}/api/v1/endpoints/live-tmux-endpoint/session-state"
    while time.monotonic() < deadline:
        result = subprocess.run(["curl", "-s", "-H", f"Authorization: Bearer {token}", url], text=True, stdout=subprocess.PIPE)
        if "fixture-session" in result.stdout:
            return result.stdout
        time.sleep(1)
    raise RuntimeError("inventory never contained the fixture session")


def main() -> int:
    """Run the offer cases and preserve terminal evidence."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--bin-dir", required=True, type=Path)
    parser.add_argument("--provider", required=True, type=Path)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--session", default="offer-audit")
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()
    for value in (args.runtime, args.bin_dir, args.provider, args.project, args.evidence_dir):
        if not value.is_absolute():
            parser.error("all paths must be absolute")
    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    children: list[subprocess.Popen] = []
    subprocess.run(["tmux", "kill-session", "-t", args.session], stderr=subprocess.DEVNULL)
    try:
        children, api_port, token = start_services(args.runtime, args.bin_dir, args.provider, args.project)
        wait_inventory(api_port, token, 60)
        launch = "env -u AGENT_CLUSTER_SERVER_URL -u AGENT_CLUSTER_TOKEN " + str(args.bin_dir / "agent-cluster-cli") + " interactive"
        subprocess.run(["tmux", "new-session", "-d", "-s", args.session, "-x", "180", "-y", "40", "-n", "cli", launch], check=True)
        target = f"{args.session}:cli"
        wait_prompt(target, "", 30)
        cases: list[tuple[str, list[str]]] = [
            ("offer-04-workspace", ["hello world"]),
            ("offer-01-select", ["list", "cd 1"]),
            ("offer-03-decline", ["hello world", "n"]),
            ("offer-02-accept", ["hello world", "y"]),
            ("offer-05-help", ["help"]),
        ]
        results = []
        for case, steps in cases:
            transcript = []
            for step in steps:
                transcript.append({"input": step, "output": send_line(target, step, args.timeout)})
            (args.evidence_dir / f"{case}.json").write_text(json.dumps(transcript, ensure_ascii=False, indent=2), encoding="utf-8")
            results.append({"case": case, "steps": len(steps)})
        (args.evidence_dir / "run-ledger.jsonl").write_text(
            "\n".join(json.dumps(record, sort_keys=True) for record in results) + "\n", encoding="utf-8"
        )
        print(json.dumps({"status": "CAPTURED", "cases": results}, sort_keys=True))
        return 0
    finally:
        subprocess.run(["tmux", "kill-session", "-t", args.session], stderr=subprocess.DEVNULL)
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=10)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(1))
    raise SystemExit(main())
