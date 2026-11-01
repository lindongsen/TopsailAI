#!/bin/sh
set -eu
: "${AGENT_CLUSTER_CLI:?set AGENT_CLUSTER_CLI to the built CLI path}"
exec "$AGENT_CLUSTER_CLI" --server-url "${AGENT_CLUSTER_SERVER_URL:?set AGENT_CLUSTER_SERVER_URL}" --token "${AGENT_CLUSTER_TOKEN:?set AGENT_CLUSTER_TOKEN}" interactive
