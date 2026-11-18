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


def adapter_document(provider: Path, capabilities: Path | None, provider_args: list[str]) -> dict[str, object]:
    """Return the one adapter document the Endpoint is configured with.

    The capability descriptor is embedded here rather than passed through a
    separate variable because the Endpoint reads capabilities from the adapter
    document only. A descriptor supplied as a file is parsed and re-encoded, so a
    malformed file fails at startup with the parser's own message instead of
    reaching the Endpoint as an opaque string.

    Provider arguments are a separate list rather than words appended to the
    command, because the Endpoint executes the command as one executable path and
    never re-splits it. A provider that needs a flag therefore needs this field,
    and a path containing a space stays one path.
    """
    document: dict[str, object] = {
        "adapter_id": "topsailai-live",
        "provider_type": "genericcli",
        "command": str(provider),
        "timeout_ms": 60000,
    }
    if provider_args:
        document["args"] = list(provider_args)
    if capabilities is not None:
        document["capabilities"] = json.loads(capabilities.read_text(encoding="utf-8"))
    return document


def api_port_accepts(port: int) -> bool:
    """Report whether the API port currently accepts a TCP connection."""
    with socket.socket() as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def log_tail(runtime: Path, name: str, limit: int = 20) -> str:
    """Return the last lines of one child log so a startup failure is diagnosable."""
    path = runtime / f"{name}.log"
    if not path.is_file():
        return f"{name} log: missing"
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return f"{name} log tail:\n" + "\n".join(lines[-limit:])


def wait_until_ready(children, planned, api_port: int, runtime: Path, timeout_seconds: float) -> None:
    """Wait until the API port accepts a connection and every child is alive.

    Readiness is the observable fact that the API port answers, not a fixed
    sleep: a slow start is waited for, and a fast failure is reported with the
    child log instead of being mistaken for readiness.
    """
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        for name, child in zip((name for name, _, _ in planned), children):
            if child.poll() is not None:
                raise RuntimeError(f"{name} exited during startup with {child.returncode}\n{log_tail(runtime, name)}")
        if api_port_accepts(api_port):
            return
        time.sleep(0.1)
    tails = "\n".join(log_tail(runtime, name) for name, _, _ in planned)
    raise RuntimeError(f"services did not become ready within {timeout_seconds}s\n{tails}")


def wait_for_exit_or_timeout(children, timeout_seconds: float, tolerate_child_exit: bool = False) -> bool:
    """Wait until a child exits or the bounded run time elapses.

    Returns True when a child exited, False when the timeout elapsed. A zero
    timeout keeps the original behaviour of waiting until interrupted.

    tolerate_child_exit keeps the supervisor alive after a child exits. A
    re-home scenario stops one Server on purpose, and that stop is the event
    under test: tearing down the remaining children at that moment would destroy
    the very thing the scenario is observing. The default stays strict, so every
    existing scenario still treats an unexpected child exit as a failure.
    """
    deadline = None if timeout_seconds <= 0 else time.monotonic() + timeout_seconds
    while True:
        if not tolerate_child_exit and any(child.poll() is not None for child in children):
            return True
        if deadline is not None and time.monotonic() >= deadline:
            print(f"timeout reached after {timeout_seconds}s", flush=True)
            return False
        time.sleep(0.2)


def main() -> int:
    """Run exact owned service children until interrupted or one child exits."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--bin-dir", required=True, type=Path)
    parser.add_argument("--provider-home", required=True, type=Path)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--provider", required=True, type=Path)
    parser.add_argument(
        "--provider-arg",
        action="append",
        default=[],
        metavar="ARG",
        help="one argument passed to the provider executable; repeat for several",
    )
    parser.add_argument("--role", choices=("both", "server", "endpoint"), default="both")
    parser.add_argument("--allowlist", type=Path, help="optional command allowlist file for the endpoint")
    parser.add_argument("--capabilities", type=Path, help="optional capability descriptor file the endpoint declares")
    parser.add_argument("--startup-timeout-seconds", type=float, default=30.0, help="how long to wait for the API port to accept a connection")
    parser.add_argument("--timeout-seconds", type=float, default=0.0, help="stop after this many seconds; zero waits until interrupted")
    # The Endpoint authentication mode is opt-in so every existing scenario keeps
    # the permissive Endpoint it had before. An Endpoint with no policy directory
    # accepts every caller, which is why the default smoke never exercised the
    # credential path at all: it proved the Server credential and nothing else.
    parser.add_argument(
        "--endpoint-auth-mode",
        choices=("bearer", "hmac"),
        help="Endpoint credential mode; omit to leave the Endpoint on its built-in default",
    )
    parser.add_argument(
        "--endpoint-policy-dir",
        type=Path,
        help="Endpoint-local access policy directory; required to enforce any credential",
    )
    # A second Server is opt-in so every existing scenario keeps its exact
    # single-Server topology. It is a genuinely independent Server with its own
    # database and API port, which is what a re-home moves an Endpoint between.
    parser.add_argument("--secondary-server", action="store_true", help="start a second independent Server for re-home scenarios")
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
    # The secondary Server gets its own ports and its own database file. Sharing
    # either would make it a replica of the primary rather than an independent
    # Server, and a re-home between replicas would prove nothing about the
    # independent-Server case this feature exists for.
    secondary_api_port = 0
    secondary_channel_port = 0
    secondary_token = ""
    if args.secondary_server:
        secondary_api_port = available_port()
        secondary_channel_port = available_port()
        # The second Server gets its own bearer token. Two Servers that accept the
        # same credential are not independent from a client's point of view: a
        # profile that selected the wrong token would still be accepted, so the
        # profile feature could not be discriminated and a re-home would look
        # correct even if the client kept presenting the primary Server's token.
        # A real second Server has its own operator credential.
        secondary_token = secrets.token_urlsafe(32)
        # The ports and the token are persisted into the same configuration
        # document the primary values already live in, so a caller reads every
        # value from one machine-readable file. Parsing them back out of the
        # human-readable READY line is not an option: that line contains both
        # "api_port=" and "secondary_api_port=", and any pattern matching the
        # former also matches the tail of the latter.
        config["secondary_api_port"] = secondary_api_port
        config["secondary_channel_port"] = secondary_channel_port
        config["secondary_token"] = secondary_token
        config_path = args.runtime / CONFIG_NAME
        config_path.write_text(json.dumps(config), encoding="utf-8")
        config_path.chmod(0o600)
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
        # The bearer mode is selected explicitly. HMAC is the built-in default,
        # and it requires a key_id.secret credential, so a script that supplies
        # only a bare token would fail at startup instead of exercising the API
        # it is meant to prove. The harness selects bearer for the same reason.
        "AGENT_CLUSTER_SERVER_AUTH_MODE": "bearer",
        "AGENT_CLUSTER_SERVER_AUTH_TOKEN": token,
        "AGENT_CLUSTER_TLS_CERTIFICATE_FILE": str(certs / "server.pem"),
        "AGENT_CLUSTER_TLS_KEY_FILE": str(certs / "server.key"),
    }
    # The secondary Server shares the CA and the Server certificate with the
    # primary, because the Endpoint is configured with one CA and one client
    # certificate. Sharing the certificate does not make the two Servers one
    # deployment: identity is the database, and these are two databases.
    #
    # It does not share the bearer token. A client that selected the wrong
    # profile must be refused, and that is only observable when the two Servers
    # accept different credentials.
    secondary_env = base | {
        "AGENT_CLUSTER_SERVER_API_LISTEN_ADDR": f"127.0.0.1:{secondary_api_port}",
        "AGENT_CLUSTER_SERVER_CHANNEL_LISTEN_ADDR": f"127.0.0.1:{secondary_channel_port}",
        "AGENT_CLUSTER_DATABASE_PATH": str(args.runtime / "server-secondary.db"),
        "AGENT_CLUSTER_SERVER_AUTH_MODE": "bearer",
        "AGENT_CLUSTER_SERVER_AUTH_TOKEN": secondary_token,
        "AGENT_CLUSTER_TLS_CERTIFICATE_FILE": str(certs / "server.pem"),
        "AGENT_CLUSTER_TLS_KEY_FILE": str(certs / "server.key"),
    }
    # The Endpoint dials the primary Server first and the secondary Server second.
    # The ordered list spelling is used only when a second Server exists, so the
    # single-Server scenarios keep the exact configuration they had before and a
    # regression in the list path cannot hide behind an unused variable.
    endpoint_env = base | {
        "AGENT_CLUSTER_ENDPOINT_ID": "live-tmux-endpoint",
        "AGENT_CLUSTER_DATABASE_PATH": str(args.runtime / "endpoint.db"),
        "AGENT_CLUSTER_TLS_CERTIFICATE_FILE": str(certs / "client.pem"),
        "AGENT_CLUSTER_TLS_KEY_FILE": str(certs / "client.key"),
        "AGENT_CLUSTER_ENDPOINT_ADAPTERS": json.dumps([adapter_document(args.provider, args.capabilities, args.provider_arg)]),
    }
    # The mode and the policy directory are set together, because either one alone
    # proves nothing. A mode without a policy directory leaves the Endpoint
    # permissive, so every credential is accepted and the mode is never consulted.
    # A policy directory without a mode leaves the Endpoint on its HMAC default,
    # which refuses the bearer token the harness CLI presents.
    if args.endpoint_auth_mode is not None:
        endpoint_env["AGENT_CLUSTER_ENDPOINT_AUTH_MODE"] = args.endpoint_auth_mode
    if args.endpoint_policy_dir is not None:
        if not args.endpoint_policy_dir.is_absolute():
            parser.error("--endpoint-policy-dir must be an absolute path")
        if not args.endpoint_policy_dir.is_dir():
            parser.error("--endpoint-policy-dir must name an existing directory")
        endpoint_env["AGENT_CLUSTER_ENDPOINT_ACCESS_POLICY_DIR"] = str(args.endpoint_policy_dir)
    if args.secondary_server:
        endpoint_env["AGENT_CLUSTER_ENDPOINT_CHANNEL_ADDRESSES"] = (
            f"wss://127.0.0.1:{channel_port},wss://127.0.0.1:{secondary_channel_port}"
        )
    else:
        endpoint_env["AGENT_CLUSTER_ENDPOINT_CHANNEL_ADDRESS"] = f"wss://127.0.0.1:{channel_port}"
    # A capability descriptor is optional so the same harness can prove the
    # zero-capability path, which is what an operator gets by copying the shipped
    # example configuration. When it is supplied it is embedded in the adapter
    # document rather than written to a second file, because the Endpoint reads
    # capabilities from the adapter document and nowhere else.
    if args.capabilities is not None:
        if not args.capabilities.is_absolute():
            parser.error("--capabilities must be an absolute path")
        if not args.capabilities.is_file():
            parser.error("--capabilities must name an existing file")
    # An allowlist is optional so the same harness can prove the fail-closed path
    # when the endpoint is started without one.
    if args.allowlist is not None:
        if not args.allowlist.is_absolute():
            parser.error("--allowlist must be an absolute path")
        if not args.allowlist.is_file():
            parser.error("--allowlist must name an existing file")
        endpoint_env["AGENT_CLUSTER_ENDPOINT_COMMAND_ALLOWLIST_FILE"] = str(args.allowlist)
    # The CLI loads .env.local from the directory of its own executable, so the
    # isolated configuration must live beside the binary rather than in runtime.
    #
    # Both Servers are defined as named profiles, so following the Endpoint to the
    # second Server is a selection rather than a rewrite of the client's
    # configuration. Each profile carries its own URL and its own token, because a
    # Server URL and its bearer token are one credential pair: changing them
    # separately is how one Server's token ends up presented to another Server.
    cli_environment = args.bin_dir / ".env.local"
    profile_urls = f"primary=http://127.0.0.1:{api_port}"
    profile_tokens = f"primary={token}"
    if secondary_token:
        profile_urls += f",secondary=http://127.0.0.1:{secondary_api_port}"
        profile_tokens += f",secondary={secondary_token}"
    cli_environment.write_text(
        f"AGENT_CLUSTER_CLI_SERVER_PROFILES={profile_urls}\n"
        f"AGENT_CLUSTER_CLI_SERVER_PROFILE_TOKENS={profile_tokens}\n"
        "AGENT_CLUSTER_CLI_SERVER_PROFILE=primary\n"
        # The CLI selects the same scheme the Servers above were started with.
        # HMAC is the built-in default and requires a key_id.secret credential,
        # so a bare token would be rejected before any request is sent. The
        # harness sets this explicitly for the same reason.
        "AGENT_CLUSTER_CLI_AUTH_MODE=bearer\n",
        encoding="utf-8",
    )
    cli_environment.chmod(0o600)
    # Inherited AGENT_CLUSTER_* variables take precedence over .env.local, so the
    # launch command must clear them before starting the CLI. The profile keys are
    # cleared for the same reason: an inherited selection would silently override
    # the one this file defines.
    launch = (
        "env -u AGENT_CLUSTER_CLI_SERVER_URL -u AGENT_CLUSTER_CLI_SERVER_TOKEN "
        "-u AGENT_CLUSTER_CLI_SERVER_PROFILES -u AGENT_CLUSTER_CLI_SERVER_PROFILE_TOKENS "
        "-u AGENT_CLUSTER_CLI_SERVER_PROFILE -u AGENT_CLUSTER_CLI_AUTH_MODE "
        + str(args.bin_dir / "agent-cluster-cli")
        + " interactive"
    )
    planned = []
    if args.role in ("both", "server"):
        planned.append(("server", server, server_env))
    # A second Server is optional and exists only for the re-home scenarios. It
    # owns its own database and API port, so it is a genuinely independent
    # Server rather than a replica, which is the whole point of a re-home.
    if args.secondary_server:
        planned.append(("server-secondary", server, secondary_env))
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
        wait_until_ready(children, planned, api_port, args.runtime, args.startup_timeout_seconds)
        (args.runtime / f"pids-{args.role}.json").write_text(json.dumps([child.pid for child in children]), encoding="utf-8")
        secondary_note = f" secondary_api_port={secondary_api_port}" if secondary_api_port else ""
        print(f"READY role={args.role} endpoint=live-tmux-endpoint api_port={api_port}{secondary_note}", flush=True)
        print(f"CLI {launch}", flush=True)
        # A re-home scenario stops one Server on purpose, so the supervisor must
        # survive that exit instead of tearing down the remaining children. The
        # flag is derived from the same option that starts the second Server, so
        # a single-Server scenario keeps the strict behaviour it always had.
        if wait_for_exit_or_timeout(children, args.timeout_seconds, tolerate_child_exit=args.secondary_server):
            for name, child in zip((name for name, _, _ in planned), children):
                if child.poll() is not None:
                    print(f"exited {name} pid {child.pid} code {child.returncode}", flush=True)
            return 1
        return 0
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
