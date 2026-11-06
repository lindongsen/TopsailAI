#!/bin/bash
# Author: DawsonLin
# Purpose: Install an Agent Cluster node bundle into system paths.
#
# The bundle is the unit of deployment, so installation is a bundle action:
#
#   <bundle>/
#     install-node.sh           this script
#     conf/node.conf            role configuration
#     bin/agent-cluster-<role>  the role binary
#     bin/agent-cluster-cli     the operator CLI (endpoint bundles only)
#
# Installing an endpoint also installs the CLI, because the CLI is how an
# operator on that machine reaches the Server. The CLI is installed as
# /usr/local/sbin/topsailai_agent_cluster and reads its Server address and token
# from ${HOME}/.topsailai/.topsailai_agent_cluster.env, which this script writes.
#
# Usage: install-node.sh [--install-dir <dir>] [--force]
#
#   --install-dir  destination directory for the binaries (default /usr/local/sbin)
#   --force        replace an existing per-user env file whose content differs
#
# Re-running with identical configuration is a no-op, so the script is safe to
# repeat after a bundle refresh.

set -uo pipefail

INSTALL_DIR="/usr/local/sbin"
FORCE=0
CLI_NAME="topsailai_agent_cluster"
ENV_RELATIVE_PATH=".topsailai/.topsailai_agent_cluster.env"

SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
CONFIG_FILE="${SCRIPT_DIR}/conf/node.conf"

function die() {
    echo "ERROR: $*" >&2
    exit 1
}

function usage() {
    echo "usage: $(basename "$0") [--install-dir <dir>] [--force]" >&2
    exit 2
}

while [ $# -gt 0 ]; do
    case "$1" in
        --install-dir)
            [ $# -ge 2 ] || usage
            INSTALL_DIR="$2"
            shift 2
            ;;
        --force) FORCE=1; shift ;;
        -h | --help) usage ;;
        *) die "unknown argument $1" ;;
    esac
done

# Loads the role configuration exactly as the node controller does, so the
# installer and the runtime never disagree about identity or addresses.
function load_config() {
    [ -f "${CONFIG_FILE}" ] || die "missing configuration ${CONFIG_FILE}"
    while IFS='=' read -r key _; do
        case "${key}" in
            AGENT_CLUSTER_*) unset "${key}" ;;
        esac
    done < <(env)
    set -a
    # shellcheck disable=SC1090
    . "${CONFIG_FILE}"
    set +a

    ROLE="${ROLE:-}"
    case "${ROLE}" in
        server | endpoint) ;;
        *) die "ROLE must be server or endpoint, got '${ROLE}'" ;;
    esac
}

# Quotes a value for the literal env-file parser: single quotes keep spaces and
# comment characters intact, and the parser supports no escaping inside them.
function quote_value() {
    local value="$1"
    case "${value}" in
        *"'"*) die "value must not contain a single quote" ;;
    esac
    printf "'%s'" "${value}"
}

# Installs one binary from the bundle into the destination directory.
function install_binary() {
    local source="$1"
    local target="$2"
    [ -f "${source}" ] || die "missing binary ${source}"
    install -m 0755 "${source}" "${target}" ||
        die "cannot install ${target}"
    echo "installed ${target}"
}

# Writes the per-user CLI env file, replacing it only when forced.
function write_cli_env() {
    local home="${HOME:-}"
    [ -n "${home}" ] || die "HOME is required to write the CLI env file"
    [ -n "${SERVER_API_URL:-}" ] || die "SERVER_API_URL is required to configure the CLI"
    [ -n "${AUTH_TOKEN:-}" ] || die "AUTH_TOKEN is required to configure the CLI"

    local target="${home}/${ENV_RELATIVE_PATH}"
    local content
    content=$(
        echo "# Author: DawsonLin"
        echo "# Purpose: Per-user Agent Cluster CLI configuration."
        echo "# Written by install-node.sh; the CLI reads it when the process"
        echo "# environment does not already define these keys."
        echo "AGENT_CLUSTER_SERVER_URL=$(quote_value "${SERVER_API_URL}")"
        echo "AGENT_CLUSTER_TOKEN=$(quote_value "${AUTH_TOKEN}")"
    ) || die "cannot compose ${target}"

    # Restrict only a directory this script created. An existing directory may be
    # a symlink to a shared location (for example ${HOME}/.topsailai pointing at a
    # mounted host directory), and chmod would follow that link and change the
    # permissions of the shared target.
    local env_dir
    env_dir=$(dirname "${target}")
    if [ ! -d "${env_dir}" ]; then
        mkdir -p "${env_dir}" || die "cannot create ${env_dir}"
        chmod 0700 "${env_dir}" || die "cannot restrict ${env_dir}"
    fi

    if [ -f "${target}" ]; then
        if [ "$(cat "${target}")" = "${content}" ]; then
            chmod 0600 "${target}"
            echo "unchanged ${target}"
            return 0
        fi
        if [ "${FORCE}" -ne 1 ]; then
            die "${target} already exists with different content; re-run with --force to replace it"
        fi
    fi

    printf '%s\n' "${content}" >"${target}" || die "cannot write ${target}"
    chmod 0600 "${target}" || die "cannot restrict ${target}"
    echo "wrote ${target}"
}

load_config

[ -d "${INSTALL_DIR}" ] || mkdir -p "${INSTALL_DIR}" || die "cannot create ${INSTALL_DIR}"

install_binary "${SCRIPT_DIR}/bin/agent-cluster-${ROLE}" "${INSTALL_DIR}/agent-cluster-${ROLE}"

# Only an endpoint bundle carries the CLI, and only an endpoint needs it: the
# operator on that machine uses it to reach the Server.
if [ "${ROLE}" = "endpoint" ]; then
    install_binary "${SCRIPT_DIR}/bin/agent-cluster-cli" "${INSTALL_DIR}/${CLI_NAME}"
    write_cli_env
else
    echo "skipped CLI install: the ${ROLE} role does not carry the operator CLI"
fi

echo "node install complete: role=${ROLE} dir=${INSTALL_DIR}"
