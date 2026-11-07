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
#     lib/cli-env.sh            shared per-user env-file writer
#
# Installing an endpoint also installs the CLI, because the CLI is how an
# operator on that machine reaches the Server. The CLI keeps its native name
# /usr/local/sbin/agent-cluster-cli, and /usr/local/sbin/topsailai_agent_cluster
# is a symlink to it, so both spellings reach the same binary. It reads its
# Server address and token from ${HOME}/.topsailai/.topsailai_agent_cluster.env,
# which this script writes.
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
CLI_NAME="agent-cluster-cli"
CLI_ALIAS="topsailai_agent_cluster"

SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
CONFIG_FILE="${SCRIPT_DIR}/conf/node.conf"
CLI_ENV_LIB="${SCRIPT_DIR}/lib/cli-env.sh"

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

# Installs one binary from the bundle into the destination directory.
function install_binary() {
    local source="$1"
    local target="$2"
    [ -f "${source}" ] || die "missing binary ${source}"
    install -m 0755 "${source}" "${target}" ||
        die "cannot install ${target}"
    echo "installed ${target}"
}

# Points the product-facing alias at the CLI that was just installed. The alias
# is a relative symlink because both names live in the same directory, so the
# link keeps working when the install directory is relocated. A regular file left
# by an older layout is replaced, and the replacement is reported because it
# removes a file.
function install_cli_alias() {
    local target="${INSTALL_DIR}/${CLI_ALIAS}"
    if [ -f "${target}" ] && [ ! -L "${target}" ]; then
        rm -f "${target}" || die "cannot remove the old ${target}"
        echo "removed the old regular file ${target}"
    fi
    ln -sfn "${CLI_NAME}" "${target}" || die "cannot link ${target}"
    echo "linked ${target} -> ${CLI_NAME}"
}

# Writes the per-user CLI env file, replacing it only when forced. The writer is
# shared with the Debian package postinst so both deployment paths produce the
# same file with the same permissions.
function write_cli_env() {
    [ -f "${CLI_ENV_LIB}" ] || die "missing shared library ${CLI_ENV_LIB}"
    # shellcheck source=lib/cli-env.sh
    . "${CLI_ENV_LIB}"
    cli_env_write "${HOME:-}" "${SERVER_API_URL:-}" "${AUTH_TOKEN:-}" "${FORCE}" ||
        die "cannot write the per-user CLI env file"
}

load_config

[ -d "${INSTALL_DIR}" ] || mkdir -p "${INSTALL_DIR}" || die "cannot create ${INSTALL_DIR}"

install_binary "${SCRIPT_DIR}/bin/agent-cluster-${ROLE}" "${INSTALL_DIR}/agent-cluster-${ROLE}"

# Only an endpoint bundle carries the CLI, and only an endpoint needs it: the
# operator on that machine uses it to reach the Server.
if [ "${ROLE}" = "endpoint" ]; then
    install_binary "${SCRIPT_DIR}/bin/agent-cluster-cli" "${INSTALL_DIR}/${CLI_NAME}"
    install_cli_alias
    write_cli_env
else
    echo "skipped CLI install: the ${ROLE} role does not carry the operator CLI"
fi

echo "node install complete: role=${ROLE} dir=${INSTALL_DIR}"
