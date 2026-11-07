#!/bin/bash
# Author: DawsonLin
# Purpose: Build a Debian package for one Agent Cluster node role.
#
# The package carries the same payload as a node bundle, laid out so the whole
# product is visible in one directory:
#
#   /opt/agent-cluster/            program payload, one directory per node
#     agent-clusterctl             controller
#     bin/agent-cluster-<role>     role binary
#     bin/agent-cluster-cli        operator CLI (endpoint only)
#     bin/agent-cluster-node-setup env-file regenerator
#     lib/cli-env.sh               shared env writer
#     conf -> /etc/agent-cluster   configuration conffiles
#     certs -> /etc/agent-cluster/certs
#     data -> /var/lib/agent-cluster
#     logs -> /var/log/agent-cluster
#     run -> /run/agent-cluster
#   /usr/local/sbin/agent-clusterctl, agent-cluster-<role>, agent-cluster-cli,
#   topsailai_agent_cluster, topsailai2, agent-cluster-node-setup
#                                  symlinks to the payload above
#
# Configuration, TLS material, state, logs and pid files stay in /etc, /var/lib,
# /var/log and /run: conffiles must live in /etc to survive an upgrade, and
# mutable state must not share a directory with immutable payload. They appear
# inside /opt/agent-cluster as symlinks, so the operator still sees one folder.
#
# A machine has one role, so the two role packages conflict: they both own
# /etc/agent-cluster/node.conf and the single agent-clusterctl entry point. A
# host that must run both roles uses the bundle path instead.
#
# Binaries are built statically (CGO disabled) so the package does not depend on
# the node libc; the SQLite driver is pure Go, so nothing is lost.
#
# Usage:
#   make-deb.sh --role <node|server|endpoint> --dest <dir> [options]
#
# Options:
#   --role      node, server or endpoint (required)
#   --dest      directory that receives the .deb (required)
#   --version   package version (default: derived from git)
#   --revision  package revision (default: 1)
#   --arch      target architecture (default: dpkg --print-architecture)
#   --config    role configuration template (default: conf/node.<role>.conf.example)
#   --cert      leaf certificate to embed (default: development certificate)
#   --key       private key paired with --cert (default: development key)
#   --ca        CA certificate (default: .tmp/local-cluster/certs/ca.pem)
#   --adapters  adapter JSON for the endpoint role; replaces the template value
#   --keep      keep the staging tree for inspection

set -uo pipefail

SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
PROJECT_DIR=$(dirname "${SCRIPT_DIR}")
LOCAL_CERTS="${PROJECT_DIR}/.tmp/local-cluster/certs"

# The program payload lives in one directory so a node can be inspected, backed
# up or removed as a unit. Entry points are symlinks in /usr/local/sbin, which is
# on the default PATH. Configuration, state, logs and pid files stay in /etc,
# /var/lib, /var/log and /run, and appear inside OPT_DIR as symlinks.
OPT_DIR="/opt/agent-cluster"
SBIN_DIR="/usr/local/sbin"
# Debian compares the epoch before every other component, so a change of version
# scheme can never sort below an already-installed package. The hash-derived
# versions installed before this convention (for example 4e160caf-4) sort above
# any tag-derived 1.x version, so the epoch is what turns the tag scheme into an
# upgrade instead of a downgrade. Bump it only when the scheme changes again.
DEB_EPOCH="1"

ROLE=""
DEST=""
VERSION=""
REVISION="1"
ARCH=""
CONFIG=""
CERT=""
KEY=""
CA="${LOCAL_CERTS}/ca.pem"
ADAPTERS=""
KEEP=0
PRINT_VERSION=0

function die() {
    echo "ERROR: $*" >&2
    exit 1
}

function warn() {
    echo "WARNING: $*" >&2
}

function usage() {
    sed -n '2,40p' "$0" | sed 's/^# \{0,1\}//' >&2
    exit 2
}

while [ $# -gt 0 ]; do
    case "$1" in
        --role) ROLE="${2:-}"; shift 2 ;;
        --dest) DEST="${2:-}"; shift 2 ;;
        --version) VERSION="${2:-}"; shift 2 ;;
        --revision) REVISION="${2:-}"; shift 2 ;;
        --arch) ARCH="${2:-}"; shift 2 ;;
        --config) CONFIG="${2:-}"; shift 2 ;;
        --cert) CERT="${2:-}"; shift 2 ;;
        --key) KEY="${2:-}"; shift 2 ;;
        --ca) CA="${2:-}"; shift 2 ;;
        --adapters) ADAPTERS="${2:-}"; shift 2 ;;
        --keep) KEEP=1; shift ;;
        --print-version) PRINT_VERSION=1; shift ;;
        -h | --help) usage ;;
        *) die "unknown argument $1" ;;
    esac
done

# A Debian version must start with a digit and must not carry a hyphen in the
# upstream part, so a tag-derived description is normalised before use. The
# commit count keeps successive builds of the same tag ordered, and the short
# hash keeps two builds of the same count distinguishable.
#
# A dirty tree sorts BELOW the clean build of the same commit: `~` is the Debian
# "sorts before" marker, while the `+` that a plain hyphen would become sorts
# above. A local experiment build must never outrank the committed build it was
# derived from, otherwise installing it silently pins the host to an uncommitted
# tree that no later clean build can upgrade.
function default_version() {
    local described
    described=$(cd "${PROJECT_DIR}" && git describe --tags --always --dirty 2>/dev/null) || described=""
    if [ -z "${described}" ]; then
        echo "0.0.0"
        return
    fi
    described="${described#v}"
    described="${described//-dirty/~dirty}"
    described="${described//-/+}"
    described="${described//_/+}"
    case "${described}" in
        [0-9]*) echo "${described}" ;;
        *) echo "0.0.0+git${described}" ;;
    esac
}

# Resolving the version is a separate mode so that one `make deb` run can pin a
# single version for every package. Each invocation otherwise re-derives it from
# git, and a commit landing between two builds yields a set whose role packages
# depend on a controller version that was never produced.
if [ "${PRINT_VERSION}" -eq 1 ]; then
    [ -n "${VERSION}" ] || VERSION=$(default_version)
    echo "${VERSION}"
    exit 0
fi

case "${ROLE}" in
    node | server | endpoint) ;;
    *) die "--role must be node, server or endpoint" ;;
esac
[ -n "${DEST}" ] || die "--dest is required"

[ -n "${VERSION}" ] || VERSION=$(default_version)
[ -n "${ARCH}" ] || ARCH=$(dpkg --print-architecture 2>/dev/null) ||
    die "cannot determine the target architecture; pass --arch"
FULL_VERSION="${VERSION}-${REVISION}"
# The epoch belongs in the control Version field only. A colon in a file name
# breaks scp and several artifact steps, so the file keeps the plain version and
# dpkg still compares the epoch carried inside the package.
CONTROL_VERSION="${DEB_EPOCH}:${FULL_VERSION}"
PACKAGE="agent-cluster-${ROLE}"
MAINTAINER="DawsonLin <dawson@yunify.com>"

BUILD_ROOT="${PROJECT_DIR}/.tmp/deb/build/${ROLE}"
PKG_ROOT="${BUILD_ROOT}/root"
DEB_PATH="${DEST}/${PACKAGE}_${FULL_VERSION}_${ARCH}.deb"

function cleanup() {
    if [ "${KEEP}" -eq 1 ]; then
        echo "staging tree kept at ${BUILD_ROOT}"
        return
    fi
    rm -rf "${BUILD_ROOT}"
}
trap cleanup EXIT

rm -rf "${BUILD_ROOT}"
mkdir -p "${PKG_ROOT}/DEBIAN" "${DEST}" || die "cannot create ${BUILD_ROOT}"

# Installs one file into the package tree with an explicit mode.
function add_file() {
    local source="$1"
    local target="$2"
    local mode="$3"
    [ -f "${source}" ] || die "missing ${source}"
    mkdir -p "$(dirname "${PKG_ROOT}${target}")" || die "cannot create ${target}"
    install -m "${mode}" "${source}" "${PKG_ROOT}${target}" ||
        die "cannot install ${target}"
}

# Installs one directory into the package tree with an explicit mode.
function add_dir() {
    local target="$1"
    local mode="$2"
    mkdir -p "${PKG_ROOT}${target}" || die "cannot create ${target}"
    chmod "${mode}" "${PKG_ROOT}${target}" || die "cannot restrict ${target}"
}

# Adds a symlink to the package tree.
function add_link() {
    local target="$1"
    local destination="$2"
    mkdir -p "$(dirname "${PKG_ROOT}${target}")" || die "cannot create ${target}"
    ln -sfn "${destination}" "${PKG_ROOT}${target}" || die "cannot link ${target}"
}

# Adds the /opt layout links that make one directory show the whole product.
#
# The program payload lives under /opt/agent-cluster. Configuration, TLS material,
# state, logs and pid files stay where Debian policy puts them, and appear inside
# /opt/agent-cluster as symlinks. The controller resolves every relative path
# against its own directory, so conf/node.conf, certs/, data/, logs/ and run/ all
# resolve through these links without any absolute override in the configuration.
#
# The links are absolute because their targets are outside /opt/agent-cluster.
function add_layout_links() {
    add_link "${OPT_DIR}/conf" "/etc/agent-cluster"
    add_link "${OPT_DIR}/certs" "/etc/agent-cluster/certs"
    add_link "${OPT_DIR}/data" "/var/lib/agent-cluster"
    add_link "${OPT_DIR}/logs" "/var/log/agent-cluster"
    add_link "${OPT_DIR}/run" "/run/agent-cluster"
}

# Builds one static binary into the package tree.
function build_binary() {
    local pkg="$1"
    local target="$2"
    ( cd "${PROJECT_DIR}" && CGO_ENABLED=0 go build -trimpath -ldflags "-s -w" \
        -o "${PKG_ROOT}${target}" "${pkg}" ) ||
        die "static build failed for ${pkg}"
    chmod 0755 "${PKG_ROOT}${target}" || die "cannot set mode on ${target}"
}

# Writes the copyright file Debian policy expects under /usr/share/doc.
function add_copyright() {
    local target="/usr/share/doc/${PACKAGE}/copyright"
    mkdir -p "$(dirname "${PKG_ROOT}${target}")" || die "cannot create ${target}"
    {
        echo "Copyright (c) DawsonLin."
        echo "Internal distribution only; no public license is granted."
        echo ""
        echo "Built from the topsailai_agent_cluster project."
    } >"${PKG_ROOT}${target}" || die "cannot write ${target}"
    chmod 0644 "${PKG_ROOT}${target}"
}

# Writes the control file. Installed-Size is the on-disk size in KiB, which dpkg
# uses to plan disk usage before unpacking.
function write_control() {
    local depends="$1"
    local conflicts="$2"
    local description="$3"
    local installed_size
    installed_size=$(du -sk "${PKG_ROOT}" | cut -f1)

    {
        echo "Package: ${PACKAGE}"
        echo "Version: ${CONTROL_VERSION}"
        echo "Architecture: ${ARCH}"
        echo "Maintainer: ${MAINTAINER}"
        echo "Installed-Size: ${installed_size}"
        echo "Section: admin"
        echo "Priority: optional"
        echo "Depends: ${depends}"
        if [ -n "${conflicts}" ]; then
            echo "Conflicts: ${conflicts}"
        fi
        echo "Description: ${description}"
        echo " Agent Cluster is a provider-neutral management plane: a Server"
        echo " collects inventory from machine-scoped Endpoints and routes"
        echo " operator commands back to them."
        echo " ."
        echo " This package provides the ${ROLE} role."
    } >"${PKG_ROOT}/DEBIAN/control" || die "cannot write the control file"
    chmod 0644 "${PKG_ROOT}/DEBIAN/control"
}

# Installs the role configuration as the conffile. The template's relative paths
# are kept unchanged: the packaged controller resolves them against
# /opt/agent-cluster, where conf, certs, data, logs and run are symlinks to the
# policy locations. One configuration shape therefore serves both the bundle and
# the package, and no absolute override has to be appended.
function write_role_config() {
    local template="$1"

    add_file "${template}" "/etc/agent-cluster/node.conf" 0640

    # The endpoint package ships command-allowlist.conf, so the packaged
    # configuration must reference it. A site configuration replaces the template
    # wholesale and may not carry the key, and an empty path makes the Endpoint
    # skip loading the allowlist entirely, which permits every command instead of
    # failing closed. Append the relative path only when the configuration does
    # not already set one, so a site that points elsewhere keeps its own value.
    if [ "${ROLE}" = "endpoint" ]; then
        if ! grep -qE '^[[:space:]]*COMMAND_ALLOWLIST_FILE=' \
            "${PKG_ROOT}/etc/agent-cluster/node.conf"; then
            {
                echo ""
                echo "# The package ships this conffile; conf/ resolves through the"
                echo "# /opt/agent-cluster layout to /etc/agent-cluster."
                echo "COMMAND_ALLOWLIST_FILE=conf/command-allowlist.conf"
            } >>"${PKG_ROOT}/etc/agent-cluster/node.conf" ||
                die "cannot append the allowlist path"
        fi
    fi

    # An adapter override is appended because the last assignment wins and the
    # value must stay single-quoted for the shell that sources it.
    if [ -n "${ADAPTERS}" ]; then
        [ "${ROLE}" = "endpoint" ] || die "--adapters only applies to the endpoint role"
        case "${ADAPTERS}" in
            *"'"*) die "--adapters must not contain a single quote" ;;
        esac
        {
            echo ""
            echo "# Adapter override supplied when the package was built."
            echo "ADAPTERS='${ADAPTERS}'"
        } >>"${PKG_ROOT}/etc/agent-cluster/node.conf" ||
            die "cannot append the adapter override"
    fi

    echo "/etc/agent-cluster/node.conf" >"${PKG_ROOT}/DEBIAN/conffiles" ||
        die "cannot write conffiles"
    # The allowlist is a conffile too: an operator edits it in place, so an upgrade
    # must not silently replace the policy in force with the shipped default.
    if [ "${ROLE}" = "endpoint" ]; then
        echo "/etc/agent-cluster/command-allowlist.conf" >>"${PKG_ROOT}/DEBIAN/conffiles" ||
            die "cannot register the allowlist conffile"
    fi
    chmod 0644 "${PKG_ROOT}/DEBIAN/conffiles"
}

# Warns about values a real deployment must replace before the package is used.
function warn_placeholders() {
    local config="$1"
    if grep -q "replace-with-a-real-token" "${config}"; then
        warn "the configuration still holds the placeholder AUTH_TOKEN; pass --config with a real configuration"
    fi
    if grep -q "127.0.0.1" "${config}"; then
        warn "the configuration still points at 127.0.0.1; pass --config with the site addresses"
    fi
}

# Resolves the TLS material, defaulting to the development certificates so a
# local package can be built without extra arguments.
function resolve_tls() {
    if [ -z "${CERT}" ]; then
        case "${ROLE}" in
            server) CERT="${LOCAL_CERTS}/server.pem" ;;
            endpoint) CERT="${LOCAL_CERTS}/client.pem" ;;
        esac
        [ -n "${CERT}" ] && warn "using the development certificate ${CERT}; pass --cert for a real deployment"
    fi
    if [ -z "${KEY}" ]; then
        case "${ROLE}" in
            server) KEY="${LOCAL_CERTS}/server-key.pem" ;;
            endpoint) KEY="${LOCAL_CERTS}/client-key.pem" ;;
        esac
        [ -n "${KEY}" ] && warn "using the development key ${KEY}; pass --key for a real deployment"
    fi
    [ -f "${CERT}" ] || die "missing certificate ${CERT}"
    [ -f "${KEY}" ] || die "missing private key ${KEY}"
    [ -f "${CA}" ] || die "missing CA ${CA}"
}

# Builds the role-independent controller package.
function build_node_package() {
    add_file "${SCRIPT_DIR}/agent-clusterctl" "${OPT_DIR}/agent-clusterctl" 0755
    add_file "${SCRIPT_DIR}/lib/cli-env.sh" "${OPT_DIR}/lib/cli-env.sh" 0644
    add_file "${SCRIPT_DIR}/agent-cluster-node-setup" \
        "${OPT_DIR}/bin/agent-cluster-node-setup" 0755
    add_link "${SBIN_DIR}/agent-clusterctl" "${OPT_DIR}/agent-clusterctl"
    add_link "${SBIN_DIR}/agent-cluster-node-setup" "${OPT_DIR}/bin/agent-cluster-node-setup"
    add_copyright

    write_control "bash (>= 4.0), coreutils, dpkg" "" \
        "Agent Cluster node controller and CLI configuration helper"
}

# Builds one role package: binary, configuration, TLS material and, for the
# endpoint role, the operator CLI that reaches the Server from this node.
function build_role_package() {
    local template="${CONFIG}"
    [ -n "${template}" ] || template="${PROJECT_DIR}/conf/node.${ROLE}.conf.example"
    [ -f "${template}" ] || die "missing configuration template ${template}"
    warn_placeholders "${template}"
    resolve_tls

    build_binary "./src/main/agent-cluster-${ROLE}" "${OPT_DIR}/bin/agent-cluster-${ROLE}"
    add_link "${SBIN_DIR}/agent-cluster-${ROLE}" "${OPT_DIR}/bin/agent-cluster-${ROLE}"
    if [ "${ROLE}" = "endpoint" ]; then
        # The CLI keeps its native name, which is also the name it prints in its
        # own usage text. The product-facing aliases are symlinks to it, so every
        # spelling reaches the same binary and none is a second copy.
        build_binary "./src/main/agent-cluster-cli" "${OPT_DIR}/bin/agent-cluster-cli"
        add_link "${SBIN_DIR}/agent-cluster-cli" "${OPT_DIR}/bin/agent-cluster-cli"
        add_link "${SBIN_DIR}/topsailai_agent_cluster" "agent-cluster-cli"
        add_link "${SBIN_DIR}/topsailai2" "agent-cluster-cli"
    fi

    write_role_config "${template}"
    add_file "${CA}" "/etc/agent-cluster/certs/ca.pem" 0644
    add_file "${CERT}" "/etc/agent-cluster/certs/node.pem" 0644
    add_file "${KEY}" "/etc/agent-cluster/certs/node-key.pem" 0600
    # The endpoint configuration names conf/command-allowlist.conf, which resolves
    # through the /opt layout to this conffile. Without it the Endpoint refuses to
    # start, because a missing allowlist is a configuration error rather than an
    # implicit unrestricted policy.
    if [ "${ROLE}" = "endpoint" ]; then
        add_file "${PROJECT_DIR}/conf/command-allowlist.conf.example" \
            "/etc/agent-cluster/command-allowlist.conf" 0640
    fi
    add_dir "/var/lib/agent-cluster" 0750
    add_dir "/var/log/agent-cluster" 0750
    add_layout_links
    add_copyright

    if [ "${ROLE}" = "endpoint" ]; then
        add_file "${SCRIPT_DIR}/deb/postinst.endpoint" "/DEBIAN/postinst" 0755
        write_control "agent-cluster-node (= ${CONTROL_VERSION}), bash (>= 4.0), coreutils" \
            "agent-cluster-server" \
            "Agent Cluster endpoint daemon and operator CLI"
    else
        write_control "agent-cluster-node (= ${CONTROL_VERSION}), bash (>= 4.0), coreutils" \
            "agent-cluster-endpoint" \
            "Agent Cluster server daemon"
    fi
}

case "${ROLE}" in
    node) build_node_package ;;
    server | endpoint) build_role_package ;;
esac

# --root-owner-group makes every entry root:root, so the package does not depend
# on the build account and needs no fakeroot.
dpkg-deb --root-owner-group --build "${PKG_ROOT}" "${DEB_PATH}" >/dev/null ||
    die "dpkg-deb failed for ${PACKAGE}"

echo "package ready: ${DEB_PATH}"
echo "  package : ${PACKAGE}"
echo "  version : ${CONTROL_VERSION}"
echo "  arch    : ${ARCH}"
echo "  size    : $(du -k "${DEB_PATH}" | cut -f1) KiB"
