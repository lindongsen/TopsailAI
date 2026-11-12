#!/usr/bin/env python3
"""Start isolated Agent Cluster services for the live tmux manual test."""

import argparse
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import time

CONFIG_NAME = "services.json"


def available_port() -> int:
    """Reserve and return one currently available loopback port."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def generate_certificates(runtime: Path) -> None:
    """Generate a short-lived test CA plus server and client certificates."""
    certs = runtime / "cert"
    certs.mkdir(exist_ok=True)
    log_path = runtime / "cert.log"
    with log_path.open("w", encoding="utf-8") as log:
        def run(arguments: list[str]) -> None:
            subprocess.run(arguments, check=True, stdout=log, stderr=log)

        run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(certs / "ca.key"), "-out", str(certs / "ca.pem"), "-days", "2", "-subj", "/CN=live-tmux-ca"])
        for name, common_name in (("server", "localhost"), ("client", "live-tmux-endpoint")):
            run(["openssl", "req", "-newkey", "rsa:2048", "-nodes", "-keyout", str(certs / f"{name}.key"), "-out", str(certs / f"{name}.csr"), "-subj", f"/CN={common_name}"])
            extension = certs / f"{name}.ext"
            extension.write_text("subjectAltName=IP:127.0.0.1,DNS:localhost,DNS:agent-cluster-server\nextendedKeyUsage=serverAuth,clientAuth\n", encoding="utf-8")
            run(["openssl", "x509", "-req", "-in", str(certs / f"{name}.csr"), "-CA", str(certs / "ca.pem"), "-CAkey", str(certs / "ca.key"), "-CAcreateserial", "-out", str(certs / f"{name}.pem"), "-days", "2", "-extfile", str(extension)])


def resolve_config(runtime: Path, role: str) -> dict[str, object]:
    """Return the shared service configuration for the requested role."""
    config_path = runtime / CONFIG_NAME
    if role == "both":
        generate_certificates(runtime)
        config: dict[str, object] = {
            "api_port": available_port(),
            "channel_port": available_port(),
            "token": secrets.token_urlsafe(32),
        }
        config_path.write_text(json.dumps(config), encoding="utf-8")
        config_path.chmod(0o600)
        return config
    if not config_path.is_file():
        if role == "endpoint":
            raise SystemExit("endpoint role requires an existing services.json from a server role")
        generate_certificates(runtime)
        config = {
            "api_port": available_port(),
            "channel_port": available_port(),
            "token": secrets.token_urlsafe(32),
        }
        config_path.write_text(json.dumps(config), encoding="utf-8")
        config_path.chmod(0o600)
        return config
    return json.loads(config_path.read_text(encoding="utf-8"))


def main() -> int:
    """Run exact owned service children until interrupted or one child exits."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--bin-dir", required=True, type=Path)
    parser.add_argument("--provider-home", required=True, type=Path)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--provider", required=True, type=Path)
    parser.add_argument("--role", choices=("both", "server", "endpoint"), default="both")
    parser.add_argument("--allowlist", type=Path, help="optional command allowlist file for the endpoint")
    parser.add_argument("--control-actions", type=Path, help="optional ctl action catalog file for the endpoint")
    args = parser.parse_args()
    for value in (args.runtime, args.bin_dir, args.provider_home, args.project, args.provider):
        if not value.is_absolute():
            parser.error("all paths must be absolute")
    args.runtime.mkdir(parents=True, exist_ok=True)
    args.project.mkdir(parents=True, exist_ok=True)
    server = args.bin_dir / "agent-cluster-server"
    endpoint = args.bin_dir / "agent-cluster-endpoint"
    if not server.is_file() or not endpoint.is_file() or not args.provider.is_file():
        parser.error("server, endpoint and provider executables must exist")
    config = resolve_config(args.runtime, args.role)
    api_port = int(config["api_port"])
    channel_port = int(config["channel_port"])
    token = str(config["token"])
    certs = args.runtime / "cert"
    base = os.environ.copy()
    for key in list(base):
        if key.startswith(("AGENT_CLUSTER_", "TOPSAILAI_SESSION", "TOPSAILAI_TASK", "TOPSAILAI_CONTEXT_", "TOPSAILAI_USER_MESSAGE")):
            base.pop(key)
    base.update({
        "TOPSAILAI_HOME": str(args.provider_home),
        "TOPSAILAI_PROJECT_WORKSPACE": str(args.project),
        "TOPSAILAI_PWD": str(args.project),
        "PYTHONDONTWRITEBYTECODE": "1",
        "AGENT_CLUSTER_TLS_CA_FILE": str(certs / "ca.pem"),
    })
    server_env = base | {
        "AGENT_CLUSTER_SERVER_API_LISTEN_ADDR": f"127.0.0.1:{api_port}",
        "AGENT_CLUSTER_SERVER_CHANNEL_LISTEN_ADDR": f"127.0.0.1:{channel_port}",
        "AGENT_CLUSTER_DATABASE_PATH": str(args.runtime / "server.db"),
        "AGENT_CLUSTER_SERVER_AUTH_TOKEN": token,
        "AGENT_CLUSTER_TLS_CERTIFICATE_FILE": str(certs / "server.pem"),
        "AGENT_CLUSTER_TLS_KEY_FILE": str(certs / "server.key"),
    }
    endpoint_env = base | {
        "AGENT_CLUSTER_ENDPOINT_CHANNEL_ADDRESS": f"wss://127.0.0.1:{channel_port}",
        "AGENT_CLUSTER_ENDPOINT_ID": "live-tmux-endpoint",
        "AGENT_CLUSTER_DATABASE_PATH": str(args.runtime / "endpoint.db"),
        "AGENT_CLUSTER_TLS_CERTIFICATE_FILE": str(certs / "client.pem"),
        "AGENT_CLUSTER_TLS_KEY_FILE": str(certs / "client.key"),
        "AGENT_CLUSTER_ENDPOINT_ADAPTERS": json.dumps([{"adapter_id": "topsailai-live", "provider_type": "topsailai", "command": str(args.provider), "timeout_ms": 60000}]),
    }
    # An allowlist is optional so the same harness can prove the fail-closed path
    # when the endpoint is started without one.
    if args.allowlist is not None:
        if not args.allowlist.is_absolute():
            parser.error("--allowlist must be an absolute path")
        if not args.allowlist.is_file():
            parser.error("--allowlist must name an existing file")
        endpoint_env["AGENT_CLUSTER_ENDPOINT_COMMAND_ALLOWLIST_FILE"] = str(args.allowlist)
    # A control action catalog is optional for the same reason: without it the
    # endpoint advertises no ctl. action and every ctl. operation is refused.
    if args.control_actions is not None:
        if not args.control_actions.is_absolute():
            parser.error("--control-actions must be an absolute path")
        if not args.control_actions.is_file():
            parser.error("--control-actions must name an existing file")
        endpoint_env["AGENT_CLUSTER_ENDPOINT_CONTROL_ACTION_FILE"] = str(args.control_actions)
    # The CLI loads .env.local from the directory of its own executable, so the
    # isolated configuration must live beside the binary rather than in runtime.
    cli_environment = args.bin_dir / ".env.local"
    cli_environment.write_text(f"AGENT_CLUSTER_SERVER_URL=http://127.0.0.1:{api_port}\nAGENT_CLUSTER_TOKEN={token}\n", encoding="utf-8")
    cli_environment.chmod(0o600)
    # Inherited AGENT_CLUSTER_* variables take precedence over .env.local, so the
    # launch command must clear them before starting the CLI.
    launch = "env -u AGENT_CLUSTER_SERVER_URL -u AGENT_CLUSTER_TOKEN " + str(args.bin_dir / "agent-cluster-cli") + " interactive"
    planned = []
    if args.role in ("both", "server"):
        planned.append(("server", server, server_env))
    if args.role in ("both", "endpoint"):
        planned.append(("endpoint", endpoint, endpoint_env))
    children: list[subprocess.Popen[bytes]] = []

    def request_stop(*_: object) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, request_stop)
    try:
        for name, executable, environment in planned:
            log = (args.runtime / f"{name}.log").open("wb")
            child = subprocess.Popen([str(executable)], cwd=args.runtime, env=environment, stdout=log, stderr=log)
            log.close()
            children.append(child)
            print(f"{name} pid {child.pid}", flush=True)
            time.sleep(1)
            if child.poll() is not None:
                raise RuntimeError(f"{name} exited during startup with {child.returncode}")
        (args.runtime / f"pids-{args.role}.json").write_text(json.dumps([child.pid for child in children]), encoding="utf-8")
        print(f"READY role={args.role} endpoint=live-tmux-endpoint api_port={api_port}", flush=True)
        print(f"CLI {launch}", flush=True)
        while all(child.poll() is None for child in children):
            time.sleep(0.2)
        for name, child in zip((name for name, _, _ in planned), children):
            if child.poll() is not None:
                print(f"exited {name} pid {child.pid} code {child.returncode}", flush=True)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=20)
                print(f"stopped pid {child.pid}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
