#!/bin/bash
# Author: DawsonLin
# Purpose: Shared writer for the per-user Agent Cluster CLI env file.
#
# The CLI reads ${HOME}/.topsailai/.topsailai_agent_cluster.env when the process
# environment does not already define the keys, so every deployment path must
# produce exactly the same file with exactly the same permissions. Two paths
# write it: scripts/install-node.sh for a copied bundle, and the Debian package
# postinst for a dpkg install. Keeping one implementation is what stops the two
# from drifting, and stops a security-relevant detail (the symlink-safe directory
# restriction below) from being fixed in only one of them.
#
# This file is a library: it defines functions and must be sourced, not executed.
# Functions return non-zero instead of exiting, so each caller keeps its own
# error policy and message prefix.

# Quotes a value for the literal env-file parser: single quotes keep spaces and
# comment characters intact, and the parser supports no escaping inside them.
function cli_env_quote_value() {
    local value="$1"
    case "${value}" in
        *"'"*) return 1 ;;
    esac
    printf "'%s'" "${value}"
}

# Writes the per-user CLI env file.
#
# Usage: cli_env_write <home> <server-url> <token> <force>
#
#   home        the user's home directory; the file is written under it
#   server-url  value for AGENT_CLUSTER_CLI_SERVER_URL
#   token       value for AGENT_CLUSTER_CLI_TOKEN
#   force       1 replaces an existing file whose content differs, 0 refuses
#
# Returns 0 when the file was written or already matched, 1 on any failure.
# Progress is reported on stdout so callers can surface it unchanged.
function cli_env_write() {
    local home="${1:-}"
    local server_url="${2:-}"
    local token="${3:-}"
    local force="${4:-0}"
    local relative_path=".topsailai/.topsailai_agent_cluster.env"

    [ -n "${home}" ] || {
        echo "ERROR: a home directory is required to write the CLI env file" >&2
        return 1
    }
    [ -n "${server_url}" ] || {
        echo "ERROR: a Server API URL is required to configure the CLI" >&2
        return 1
    }
    [ -n "${token}" ] || {
        echo "ERROR: a token is required to configure the CLI" >&2
        return 1
    }

    local target="${home}/${relative_path}"
    local quoted_url quoted_token
    quoted_url=$(cli_env_quote_value "${server_url}") || {
        echo "ERROR: the Server API URL must not contain a single quote" >&2
        return 1
    }
    quoted_token=$(cli_env_quote_value "${token}") || {
        echo "ERROR: the token must not contain a single quote" >&2
        return 1
    }

    local content
    content=$(
        echo "# Author: DawsonLin"
        echo "# Purpose: Per-user Agent Cluster CLI configuration."
        echo "# Written at install time; the CLI reads it when the process"
        echo "# environment does not already define these keys."
        echo "AGENT_CLUSTER_CLI_SERVER_URL=${quoted_url}"
        echo "AGENT_CLUSTER_CLI_TOKEN=${quoted_token}"
    ) || {
        echo "ERROR: cannot compose ${target}" >&2
        return 1
    }

    # Restrict only a directory this function created. An existing directory may
    # be a symlink to a shared location (for example ${HOME}/.topsailai pointing
    # at a mounted host directory), and chmod would follow that link and change
    # the permissions of the shared target.
    local env_dir
    env_dir=$(dirname "${target}")
    if [ ! -d "${env_dir}" ]; then
        mkdir -p "${env_dir}" || {
            echo "ERROR: cannot create ${env_dir}" >&2
            return 1
        }
        chmod 0700 "${env_dir}" || {
            echo "ERROR: cannot restrict ${env_dir}" >&2
            return 1
        }
    fi

    if [ -f "${target}" ]; then
        if [ "$(cat "${target}")" = "${content}" ]; then
            chmod 0600 "${target}" || {
                echo "ERROR: cannot restrict ${target}" >&2
                return 1
            }
            echo "unchanged ${target}"
            return 0
        fi
        if [ "${force}" != "1" ]; then
            echo "ERROR: ${target} already exists with different content; re-run with --force to replace it" >&2
            return 1
        fi
    fi

    printf '%s\n' "${content}" >"${target}" || {
        echo "ERROR: cannot write ${target}" >&2
        return 1
    }
    chmod 0600 "${target}" || {
        echo "ERROR: cannot restrict ${target}" >&2
        return 1
    }
    echo "wrote ${target}"
}
