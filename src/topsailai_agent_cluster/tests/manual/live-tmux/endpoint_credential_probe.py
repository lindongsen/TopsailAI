#!/usr/bin/env python3
"""Probe the Endpoint credential contract against a live cluster.

This script is the automated counterpart of the interactive procedure for the
Endpoint credential. It talks to the real Server over HTTP and lets the real
Endpoint verify the credential, so it proves the wire contract rather than a Go
function in isolation.

Two facts are asserted, and they are different facts:

1. The Server credential and the Endpoint credential are independent. The Server
   credential is a bearer token in the Authorization header and terminates at the
   Server. The Endpoint credential travels in X-Endpoint-Auth and is verified by
   the Endpoint. A request can therefore be authenticated to the Server and
   refused by the Endpoint, which is exactly what a wrong signature produces.

2. The refusal class is distinguishable. A credential that cannot be proven is
   refused as an authentication failure (401 credential_rejected), while a proven
   credential without a grant is refused as a policy decision (403
   policy_denied). Collapsing the two would send an operator to edit a policy
   file that is already correct.

The signed string is rebuilt here from the documented grammar rather than by
calling into the Go implementation, because a probe that reuses the signer cannot
detect a signer that is wrong in the same way on both sides.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import secrets
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HMAC_SCHEME = "AC-HMAC-SHA256"
ENDPOINT_AUTH_HEADER = "X-Endpoint-Auth"
ENDPOINT_TOKEN_HEADER = "X-Endpoint-Token"
LAUNCH_PATH = "/api/v1/launch-options"


def log(message: str) -> None:
    print(message, flush=True)


def die(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr, flush=True)
    raise SystemExit(1)


def body_digest(body: bytes) -> str:
    """Return the digest the signed string uses for a request body."""
    if not body:
        return "-"
    return hashlib.sha256(body).hexdigest()


def request_digest(method: str, request_uri: str, body: bytes) -> str:
    """Return the digest that binds a credential to one exact request."""
    material = f"{method}\n{request_uri}\n{body_digest(body)}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def canonical_frame_request(
    operation: str, endpoint_id: str, payload_digest: str, timestamp_ms: int, nonce: str
) -> str:
    """Return the signed string for one Endpoint credential.

    The fields are newline separated in a fixed order with no optional entries, so
    one request has exactly one encoding. The request ID is deliberately absent:
    the Server mints it, so a caller cannot predict it and could not sign it.
    """
    if not payload_digest:
        payload_digest = "-"
    return "\n".join(
        [HMAC_SCHEME, operation, endpoint_id, payload_digest, str(timestamp_ms), nonce]
    )


def sign(secret: str, message: str) -> str:
    """Return the hex HMAC-SHA256 of message under secret."""
    return hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


def parse_pair(pair: str) -> tuple[str, str]:
    """Split a key_id.secret credential into its two parts."""
    key_id, separator, secret = pair.partition(".")
    if not separator or not key_id or not secret:
        die(f"credential {pair!r} is not in key_id.secret form")
    return key_id, secret


def signed_header(pair: str, operation: str, endpoint_id: str, digest: str) -> str:
    """Return the X-Endpoint-Auth value proving possession of the pair's secret."""
    key_id, secret = parse_pair(pair)
    timestamp_ms = int(time.time() * 1000)
    nonce = secrets.token_hex(16)
    signature = sign(secret, canonical_frame_request(operation, endpoint_id, digest, timestamp_ms, nonce))
    return f"{HMAC_SCHEME} key_id={key_id}, ts={timestamp_ms}, nonce={nonce}, sig={signature}"


def call(
    api_port: int,
    server_token: str,
    endpoint_id: str,
    endpoint_headers: dict[str, str],
) -> tuple[int, dict[str, object]]:
    """Send one launch query and return its status and decoded envelope."""
    request_uri = f"{LAUNCH_PATH}?endpoint_id={endpoint_id}"
    url = f"http://127.0.0.1:{api_port}{request_uri}"
    request = urllib.request.Request(url, method="GET")
    request.add_header("Authorization", f"Bearer {server_token}")
    for name, value in endpoint_headers.items():
        request.add_header(name, value)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8")
        try:
            return error.code, json.loads(raw)
        except json.JSONDecodeError:
            die(f"HTTP {error.code} with a non-JSON body: {raw}")


def envelope_code(envelope: dict[str, object]) -> str:
    """Return the machine code of a response envelope as a string."""
    code = envelope.get("code")
    if isinstance(code, str):
        return code
    if isinstance(code, int):
        return str(code)
    return ""


def assert_status(actual: int, expected: int, label: str) -> None:
    if actual != expected:
        die(f"{label}: status={actual}, want {expected}")


def assert_code(envelope: dict[str, object], expected: str, label: str) -> None:
    actual = envelope_code(envelope)
    if actual != expected:
        die(f"{label}: code={actual!r}, want {expected!r}; envelope={json.dumps(envelope)}")


def assert_code_absent(envelope: dict[str, object], forbidden: str, label: str) -> None:
    actual = envelope_code(envelope)
    if actual == forbidden:
        die(f"{label}: code={actual!r} must not appear; envelope={json.dumps(envelope)}")


def assert_secret_absent(envelope: dict[str, object], secret: str, label: str) -> None:
    """Assert the Server response never echoes the Endpoint secret."""
    if secret in json.dumps(envelope):
        die(f"{label}: the response contains the Endpoint secret")


def run_bearer(api_port: int, server_token: str, endpoint_id: str, token: str) -> None:
    """Prove the bearer compatibility form still authenticates the Endpoint."""
    log("== bearer mode ==")
    status, envelope = call(api_port, server_token, endpoint_id, {ENDPOINT_TOKEN_HEADER: token})
    assert_status(status, 200, "bearer credential")
    assert_code_absent(envelope, "credential_rejected", "bearer credential")
    assert_code_absent(envelope, "policy_denied", "bearer credential")
    log("BEARER_OK the legacy header authenticated the Endpoint")

    # A signed credential presented to a bearer Endpoint is refused rather than
    # compared as a token. Accepting it would compare a proof against a secret and
    # always fail with a message that blames the caller's grants.
    digest = request_digest("GET", f"{LAUNCH_PATH}?endpoint_id={endpoint_id}", b"")
    signed = signed_header("ops.s3cret", "launch.query", endpoint_id, digest)
    status, envelope = call(api_port, server_token, endpoint_id, {ENDPOINT_AUTH_HEADER: signed})
    assert_status(status, 401, "signed credential in bearer mode")
    assert_code(envelope, "credential_rejected", "signed credential in bearer mode")
    log("BEARER_SIGNED_REFUSED_OK a signed credential is not accepted as a token")


def run_hmac(api_port: int, server_token: str, endpoint_id: str, pair: str) -> None:
    """Prove the signed form authenticates, and that each failure class differs."""
    log("== hmac mode ==")
    request_uri = f"{LAUNCH_PATH}?endpoint_id={endpoint_id}"
    digest = request_digest("GET", request_uri, b"")

    # A valid signature reaches the Endpoint and the policy grants the operation.
    status, envelope = call(
        api_port, server_token, endpoint_id, {ENDPOINT_AUTH_HEADER: signed_header(pair, "launch.query", endpoint_id, digest)}
    )
    assert_status(status, 200, "valid signature")
    assert_code_absent(envelope, "credential_rejected", "valid signature")
    assert_code_absent(envelope, "policy_denied", "valid signature")
    log("HMAC_OK the signed credential authenticated the Endpoint")

    # The secret never travels, so it must never come back either.
    _, secret = parse_pair(pair)
    assert_secret_absent(envelope, secret, "valid signature")
    log("HMAC_SECRET_ABSENT_OK the response does not echo the Endpoint secret")

    # A wrong secret is an authentication failure, not a grant decision.
    wrong_pair = f"{parse_pair(pair)[0]}.{secrets.token_hex(16)}"
    status, envelope = call(
        api_port, server_token, endpoint_id, {ENDPOINT_AUTH_HEADER: signed_header(wrong_pair, "launch.query", endpoint_id, digest)}
    )
    assert_status(status, 401, "wrong secret")
    assert_code(envelope, "credential_rejected", "wrong secret")
    assert_code_absent(envelope, "policy_denied", "wrong secret")
    log("HMAC_WRONG_SECRET_OK refused as a credential, not as a policy")

    # An unsigned credential is refused rather than treated as an empty token.
    status, envelope = call(api_port, server_token, endpoint_id, {})
    assert_status(status, 401, "unsigned credential")
    assert_code(envelope, "credential_rejected", "unsigned credential")
    log("HMAC_UNSIGNED_OK an absent signature is refused")

    # A bearer token presented to an HMAC Endpoint is refused, because accepting it
    # would let any caller downgrade the mode by sending the secret in the clear.
    status, envelope = call(api_port, server_token, endpoint_id, {ENDPOINT_TOKEN_HEADER: pair})
    assert_status(status, 401, "bearer credential in hmac mode")
    assert_code(envelope, "credential_rejected", "bearer credential in hmac mode")
    log("HMAC_BEARER_REFUSED_OK the weaker form cannot downgrade the mode")

    # A replayed proof is refused, because the nonce is already spent.
    replay = signed_header(pair, "launch.query", endpoint_id, digest)
    status, envelope = call(api_port, server_token, endpoint_id, {ENDPOINT_AUTH_HEADER: replay})
    assert_status(status, 200, "first use of a proof")
    status, envelope = call(api_port, server_token, endpoint_id, {ENDPOINT_AUTH_HEADER: replay})
    assert_status(status, 401, "replayed proof")
    assert_code(envelope, "credential_rejected", "replayed proof")
    log("HMAC_REPLAY_OK a spent nonce is refused")

    # A proof signed for a different operation cannot be reused for this one.
    other_digest = request_digest("GET", f"{LAUNCH_PATH}?endpoint_id={endpoint_id}&adapter_id=other", b"")
    status, envelope = call(
        api_port,
        server_token,
        endpoint_id,
        {ENDPOINT_AUTH_HEADER: signed_header(pair, "output.read", endpoint_id, other_digest)},
    )
    assert_status(status, 401, "signature for another operation")
    assert_code(envelope, "credential_rejected", "signature for another operation")
    log("HMAC_OPERATION_BOUND_OK a proof cannot be moved to another operation")


def run_hmac_without_grant(api_port: int, server_token: str, endpoint_id: str, pair: str) -> None:
    """Prove a verified credential without a grant is refused as a policy decision."""
    log("== hmac mode without a grant ==")
    digest = request_digest("GET", f"{LAUNCH_PATH}?endpoint_id={endpoint_id}", b"")
    status, envelope = call(
        api_port, server_token, endpoint_id, {ENDPOINT_AUTH_HEADER: signed_header(pair, "launch.query", endpoint_id, digest)}
    )
    assert_status(status, 403, "verified credential without a grant")
    assert_code(envelope, "policy_denied", "verified credential without a grant")
    assert_code_absent(envelope, "credential_rejected", "verified credential without a grant")
    log("HMAC_POLICY_OK a proven credential without a grant is a policy refusal")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--mode", required=True, choices=("bearer", "hmac", "hmac-no-grant"))
    parser.add_argument("--endpoint-id", default="live-tmux-endpoint")
    parser.add_argument("--credential", required=True, help="bearer token or key_id.secret pair")
    args = parser.parse_args()

    config_path = args.runtime / "services.json"
    if not config_path.is_file():
        die(f"missing service configuration: {config_path}")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    api_port = int(config["api_port"])
    server_token = str(config["token"])

    if args.mode == "bearer":
        run_bearer(api_port, server_token, args.endpoint_id, args.credential)
    elif args.mode == "hmac":
        run_hmac(api_port, server_token, args.endpoint_id, args.credential)
    else:
        run_hmac_without_grant(api_port, server_token, args.endpoint_id, args.credential)

    log("PROBE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
