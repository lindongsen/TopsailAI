#!/bin/bash
# Author: DawsonLin
# Purpose: Install an Agent Cluster node bundle into system paths.
#
# The bundle is the unit of deployment, so installation is a bundle action:
#
#   <bundle>/
#     install-node.sh           this script
#     conf/<role>/node.conf            role configuration
#     bin/agent-cluster-<role>  the role binary
#     bin/agent-cluster-cli     the operator CLI (endpoint bundles only)
#     lib/cli-env.sh            shared per-user env-file writer
#
# Installing an endpoint also installs the CLI, because the CLI is how an
# operator on that machine reaches the Server. The CLI keeps its native name
# agent-cluster-cli, and topsailai_agent_cluster and topsailai2 are symlinks to
# it, so every spelling reaches the same binary. It reads its Server address and
# token from ${HOME}/.topsailai/.topsailai_agent_cluster.env, which this script
# writes.
#
# The binaries are installed as real files under /opt/agent-cluster/bin and
# linked from /usr/local/sbin, which is the same entry-point shape the Debian
# package produces. The controller, configuration and TLS material stay in the
# bundle, which is run in place; only the package installs them into system
# paths. A bundle install therefore adds the same commands to PATH without
# replacing the bundle as the node's configuration source.
#
# Usage: install-node.sh [--install-dir <dir>] [--payload-dir <dir>] [--force]
#
#   --install-dir  directory that receives the entry-point symlinks (default /usr/local/sbin)
#   --payload-dir  directory that receives the binaries (default /opt/agent-cluster)
#   --force        replace an existing per-user env file whose content differs
#
# Re-running with identical configuration is a no-op, so the script is safe to
# repeat after a bundle refresh.

set -uo pipefail

INSTALL_DIR="/usr/local/sbin"
PAYLOAD_DIR="/opt/agent-cluster"
FORCE=0
CLI_NAME="agent-cluster-cli"
CLI_ALIASES="topsailai_agent_cluster topsailai2"

SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
CONFIG_FILE=""
CLI_ENV_LIB="${SCRIPT_DIR}/lib/cli-env.sh"

function die() {
    echo "ERROR: $*" >&2
    exit 1
}

function usage() {
    echo "usage: $(basename "$0") [--install-dir <dir>] [--payload-dir <dir>] [--force]" >&2
    exit 2
}

while [ $# -gt 0 ]; do
    case "$1" in
        --install-dir)
            [ $# -ge 2 ] || usage
            INSTALL_DIR="$2"
            shift 2
            ;;
        --payload-dir)
            [ $# -ge 2 ] || usage
            PAYLOAD_DIR="$2"
            shift 2
            ;;
        --force) FORCE=1; shift ;;
        -h | --help) usage ;;
        *) die "unknown argument $1" ;;
    esac
done

# Selects the sole role configuration in a relocatable bundle. A bundle carrying
# both roles is ambiguous and must be installed with a role-specific bundle.
function select_config() {
    local candidates=()
    local candidate
    for candidate in "${SCRIPT_DIR}/conf/server/node.conf" "${SCRIPT_DIR}/conf/endpoint/node.conf"; do
        [ -f "${candidate}" ] && candidates+=("${candidate}")
    done
    if [ "${#candidates[@]}" -eq 1 ]; then
        CONFIG_FILE="${candidates[0]}"
        return
    fi
    if [ "${#candidates[@]}" -eq 0 ]; then
        die "no role configuration found below ${SCRIPT_DIR}/conf"
    fi
    die "multiple role configurations found; use a role-specific bundle"
}

# Loads the role configuration exactly as the node controller does, so the
# installer and the runtime never disagree about identity or addresses.
function load_config() {
    select_config
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

# Installs one binary from the bundle into the payload directory and links it
# from the entry-point directory. The payload is a real file so the bundle and the
# Debian package produce the same layout: a package cannot ship a real file where
# it ships a symlink, and `install` would follow such a symlink and overwrite the
# payload instead of replacing the link.
function install_binary() {
    local source="$1"
    local name="$2"
    local payload="${PAYLOAD_DIR}/bin/${name}"
    local link="${INSTALL_DIR}/${name}"
    [ -f "${source}" ] || die "missing binary ${source}"
    install -m 0755 "${source}" "${payload}" ||
        die "cannot install ${payload}"
    echo "installed ${payload}"
    # A regular file left by an older layout is replaced, and the replacement is
    # reported because it removes a file.
    if [ -f "${link}" ] && [ ! -L "${link}" ]; then
        rm -f "${link}" || die "cannot remove the old ${link}"
        echo "removed the old regular file ${link}"
    fi
    ln -sfn "${payload}" "${link}" || die "cannot link ${link}"
    echo "linked ${link} -> ${payload}"
}

# Points one product-facing alias at the CLI that was just installed. The alias
# is a relative symlink because both names live in the same directory, so the
# link keeps working when the entry-point directory is relocated.
function install_cli_alias() {
    local alias_name="$1"
    local target="${INSTALL_DIR}/${alias_name}"
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

[ -d "${PAYLOAD_DIR}/bin" ] || mkdir -p "${PAYLOAD_DIR}/bin" ||
    die "cannot create ${PAYLOAD_DIR}/bin"
[ -d "${INSTALL_DIR}" ] || mkdir -p "${INSTALL_DIR}" || die "cannot create ${INSTALL_DIR}"

install_binary "${SCRIPT_DIR}/bin/agent-cluster-${ROLE}" "agent-cluster-${ROLE}"

# Only an endpoint bundle carries the CLI, and only an endpoint needs it: the
# operator on that machine uses it to reach the Server.
if [ "${ROLE}" = "endpoint" ]; then
    install_binary "${SCRIPT_DIR}/bin/agent-cluster-cli" "${CLI_NAME}"
    for alias_name in ${CLI_ALIASES}; do
        install_cli_alias "${alias_name}"
    done
    write_cli_env
else
    echo "skipped CLI install: the ${ROLE} role does not carry the operator CLI"
fi

echo "node install complete: role=${ROLE} payload=${PAYLOAD_DIR} links=${INSTALL_DIR}"
