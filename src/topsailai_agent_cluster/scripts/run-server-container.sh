#!/usr/bin/env bash
# Run the Agent Cluster Server as a container on this host.
#
# The container joins bind9-net, the DNS-integrated bridge defined in
# /etc/docker/daemon.json (iptables disabled, resolver 172.19.1.254). Every
# Endpoint reaches it through the bridge gateway 172.19.1.1, which is a host
# interface and therefore stable across container recreation; the container's
# own address is pinned so a log or a probe can name it.
#
# The certificate directory is mounted read-only and the data directory
# read-write, both at the same path inside and outside the container, so a host
# path and a container path are never two names for one file.
set -euo pipefail

NAME="${NAME:-agent-cluster-server-primary}"
IMAGE="${IMAGE:-agent-cluster-server:latest}"
NETWORK="${NETWORK:-bind9-net}"
CONTAINER_IP="${CONTAINER_IP:-172.19.1.10}"
PUBLISH_IP="${PUBLISH_IP:-172.19.1.1}"
API_PORT="${API_PORT:-53680}"
CHANNEL_PORT="${CHANNEL_PORT:-53943}"
TOKEN_FILE="${TOKEN_FILE:-.tmp/container-token.txt}"
CERTS_DIR="${CERTS_DIR:-/opt/agent-cluster/certs}"
DATA_DIR="${DATA_DIR:-/opt/agent-cluster/data}"

[ -r "${TOKEN_FILE}" ] || { echo "missing token file ${TOKEN_FILE}" >&2; exit 1; }
TOKEN=$(cat "${TOKEN_FILE}")
[ -n "${TOKEN}" ] || { echo "empty token in ${TOKEN_FILE}" >&2; exit 1; }

docker rm -f "${NAME}" >/dev/null 2>&1 || true

docker run -d --name "${NAME}" \
    --restart unless-stopped \
    --network "${NETWORK}" --ip "${CONTAINER_IP}" \
    -p "${PUBLISH_IP}:${API_PORT}:${API_PORT}" \
    -p "${PUBLISH_IP}:${CHANNEL_PORT}:${CHANNEL_PORT}" \
    -v "${CERTS_DIR}:${CERTS_DIR}:ro" \
    -v "${DATA_DIR}:${DATA_DIR}" \
    -e AGENT_CLUSTER_SERVER_AUTH_TOKEN="${TOKEN}" \
    -e AGENT_CLUSTER_SERVER_API_LISTEN_ADDR=":${API_PORT}" \
    -e AGENT_CLUSTER_SERVER_CHANNEL_LISTEN_ADDR=":${CHANNEL_PORT}" \
    -e AGENT_CLUSTER_DATABASE_PATH="${DATA_DIR}/server/server.sqlite" \
    -e AGENT_CLUSTER_TLS_CA_FILE="${CERTS_DIR}/server-container/ca.pem" \
    -e AGENT_CLUSTER_TLS_CERTIFICATE_FILE="${CERTS_DIR}/server-container/node.pem" \
    -e AGENT_CLUSTER_TLS_KEY_FILE="${CERTS_DIR}/server-container/node-key.pem" \
    -e AGENT_CLUSTER_LOG_OUTPUT=stderr \
    "${IMAGE}"

echo "started ${NAME} on ${NETWORK} (${CONTAINER_IP}), published on ${PUBLISH_IP}"
