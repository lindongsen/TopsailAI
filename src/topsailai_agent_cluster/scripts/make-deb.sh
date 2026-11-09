#!/bin/bash
# Author: DawsonLin
# Purpose: Build a Debian package for one Agent Cluster node role.
#
# A node is installed from two packages: a binary package that is identical on
# every machine, and a config package that carries this site's identity. The
# split exists because a site replaces the shipped certificate with its own, and
# a certificate that lives in the binary package is overwritten on every upgrade.
#
# The binary package carries the program payload, laid out so the whole product is
# visible in one directory:
#
#   /opt/agent-cluster/            program payload, one directory per node
#     agent-clusterctl             controller
#     bin/agent-cluster-<role>     role binary
#     bin/agent-cluster-cli        operator CLI (endpoint only)
#     bin/agent-cluster-node-setup env-file regenerator
#     lib/cli-env.sh               shared env writer
#     conf/                        configuration conffiles
#     certs/                       TLS material
#     data/                        SQLite state
#     logs/                        log files
#     run/                         pid files
#   /usr/local/sbin/agent-clusterctl, agent-cluster-<role>, agent-cluster-cli,
#   topsailai_agent_cluster, topsailai2, agent-cluster-node-setup
#                                  symlinks to the payload above
#
# The config package carries conf/node.conf, certs/ca.pem, certs/node.pem and
# certs/node-key.pem, plus the endpoint allowlist and control action catalog. It is
# built per site and is not interchangeable between machines.
#
# Configuration, TLS material, state, logs and pid files are real directories
# inside /opt/agent-cluster, not symlinks into /etc, /var/lib, /var/log and /run.
# A symlinked layout silently redirects a write to whatever filesystem the link
# names, so a state directory can land on a full root filesystem while the
# operator believes it lives under /opt. dpkg honours a conffile at any absolute
# path, so an operator edit under conf/ still survives an upgrade.
#
# A machine has one role, so the two config packages conflict: they both own
# /opt/agent-cluster/conf/node.conf and the same TLS paths. A host that must run
# both roles uses the bundle path instead.
#
# Binaries are built statically (CGO disabled) so the package does not depend on
# the node libc; the SQLite driver is pure Go, so nothing is lost.
#
# Usage:
#   make-deb.sh --role <node|server|endpoint|config> --dest <dir> [options]
#
# Options:
#   --role      node, server, endpoint or config (required)
#   --dest      directory that receives the .deb (required)
#   --version   package version (default: derived from git)
#   --revision  package revision (default: 1)
#   --arch      target architecture (default: dpkg --print-architecture)
#   --config    role configuration template (default: conf/node.<role>.conf.example)
#   --config-role  role a config package configures: server or endpoint (required
#               for --role config; it also selects the default template)
#   --site      site identifier that suffixes a config package name, so two sites
#               produce distinguishable artifacts (required for --role config)
#   --cert      leaf certificate to embed (default: development certificate)
#   --key       private key paired with --cert (default: development key)
#   --ca        CA certificate (default: /opt/agent-cluster/certs/ca.pem)
#   --adapters  adapter JSON for the endpoint role; replaces the template value
#   --build-dir staging tree root (default: .tmp/deb/build)
#   --keep      keep the staging tree for inspection

set -uo pipefail

SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
PROJECT_DIR=$(dirname "${SCRIPT_DIR}")
LOCAL_CERTS="/opt/agent-cluster/certs"

# The program payload lives in one directory so a node can be inspected, backed
# up or removed as a unit. Entry points are symlinks in /usr/local/sbin, which is
# on the default PATH. Configuration, state, logs and pid files are real
# directories inside OPT_DIR, so the whole product is one real tree.
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
# A config package is built per site, so the role it configures cannot be inferred
# from the package name. --config-role names it explicitly and also selects the
# default template.
CONFIG_ROLE=""
# A config package carries one site's identity, so two sites build packages with
# identical names and versions but different contents. dpkg cannot tell them
# apart, and installing the wrong one is accepted silently. --site suffixes the
# package name so the artifact itself states which site it belongs to.
SITE=""
CERT=""
KEY=""
CA="${LOCAL_CERTS}/ca.pem"
ADAPTERS=""
# The staging tree is where the package payload is assembled before dpkg-deb
# packs it. It is separate from --dest so the output directory holds only
# finished packages, and so a caller can place the staging tree on a different
# filesystem than the artifacts.
BUILD_DIR="${PROJECT_DIR}/.tmp/deb/build"
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
    sed -n '2,63p' "$0" | sed 's/^# \{0,1\}//' >&2
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
        --config-role) CONFIG_ROLE="${2:-}"; shift 2 ;;
        --site) SITE="${2:-}"; shift 2 ;;
        --cert) CERT="${2:-}"; shift 2 ;;
        --key) KEY="${2:-}"; shift 2 ;;
        --ca) CA="${2:-}"; shift 2 ;;
        --adapters) ADAPTERS="${2:-}"; shift 2 ;;
        --build-dir) BUILD_DIR="${2:-}"; shift 2 ;;
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
    config)
        # A config package carries site data, so it must name the role it
        # configures. Without the role the server and endpoint config packages
        # would share one name and one version, and installing the second would
        # silently replace the first.
        case "${CONFIG_ROLE}" in
            server | endpoint) ;;
            *) die "--role config requires --config-role server or endpoint" ;;
        esac
        ;;
    *) die "--role must be node, server, endpoint or config" ;;
esac
[ -n "${DEST}" ] || die "--dest is required"

# Both directories are resolved to absolute paths before use. A relative value is
# taken against the caller's working directory, which is what a shell user
# expects, and resolving it here keeps the staging tree and the artifact path
# stable even though the builder changes directory while assembling the payload.
# readlink -m normalises the path without requiring it to exist yet.
DEST=$(readlink -m "${DEST}") || die "cannot resolve --dest ${DEST}"
BUILD_DIR=$(readlink -m "${BUILD_DIR}") || die "cannot resolve --build-dir ${BUILD_DIR}"
[ "${DEST}" != "${BUILD_DIR}" ] ||
    die "--dest and --build-dir must differ; the staging tree must not sit in the output directory"

[ -n "${VERSION}" ] || VERSION=$(default_version)
[ -n "${ARCH}" ] || ARCH=$(dpkg --print-architecture 2>/dev/null) ||
    die "cannot determine the target architecture; pass --arch"
FULL_VERSION="${VERSION}-${REVISION}"
# The epoch belongs in the control Version field only. A colon in a file name
# breaks scp and several artifact steps, so the file keeps the plain version and
# dpkg still compares the epoch carried inside the package.
CONTROL_VERSION="${DEB_EPOCH}:${FULL_VERSION}"
# A config package is named after the role it configures and the site it belongs
# to. The role keeps the server and endpoint config packages distinct; the site
# keeps two sites' packages distinct, because they carry identical names and
# versions but different contents and dpkg would accept the wrong one silently.
# The unsuffixed name stays available as a virtual package, so a generic binary
# package can depend on it without naming any site.
if [ "${ROLE}" = "config" ]; then
    [ -n "${SITE}" ] || die "--site is required for --role config; without it two sites build indistinguishable packages"
    case "${SITE}" in
        *[!a-z0-9-]* | "") die "--site must be lowercase letters, digits and hyphens, got '${SITE}'" ;;
    esac
    CONFIG_PACKAGE_BASE="agent-cluster-config-${CONFIG_ROLE}"
    PACKAGE="${CONFIG_PACKAGE_BASE}-${SITE}"
else
    PACKAGE="agent-cluster-${ROLE}"
fi
# The config role builds the configuration for another role, so every decision
# that depends on the role being configured reads this value instead of ROLE.
# Without it a config build would look for conf/node.config.conf.example and
# would never append the endpoint-only keys.
EFFECTIVE_ROLE="${ROLE}"
[ "${ROLE}" = "config" ] && EFFECTIVE_ROLE="${CONFIG_ROLE}"
# The control description names what the package actually provides. A config
# package provides the site configuration for a role, not the role itself, and
# saying otherwise would mislead an operator reading dpkg output.
if [ "${ROLE}" = "config" ]; then
    ROLE_PHRASE="the ${EFFECTIVE_ROLE} configuration for this site"
else
    ROLE_PHRASE="the ${ROLE} role"
fi
MAINTAINER="DawsonLin <dawson@yunify.com>"

BUILD_ROOT="${BUILD_DIR}/${ROLE}"
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

# Adds the /opt layout directories that make one directory show the whole product.
#
# The program payload lives under /opt/agent-cluster, and configuration, TLS
# material, state, logs and pid files are real directories beside the controller
# rather than symlinks into /etc, /var/lib, /var/log and /run. The controller
# resolves every relative path against its own directory, so conf/node.conf,
# certs/, data/, logs/ and run/ resolve without any absolute override in the
# configuration.
#
# Real directories are deliberate: a symlinked layout silently redirects a write
# to whatever filesystem the link names, so a state directory can land on a full
# root filesystem while the operator believes it lives under /opt. One real tree
# also makes backup, removal and inspection a single-path operation.
#
# run/ is created empty on purpose. It holds pid files only, so a package must not
# ship a stale pid that would make the controller believe a daemon is running.
function add_layout_dirs() {
    add_dir "${OPT_DIR}/conf" 0755
    add_dir "${OPT_DIR}/certs" 0755
    add_dir "${OPT_DIR}/data" 0750
    add_dir "${OPT_DIR}/logs" 0750
    add_dir "${OPT_DIR}/run" 0755
}

# Adds only the directories the config package populates. State, logs and pid
# files belong to the binary package, so a config package does not claim them.
# Declaring conf/ and certs/ in both packages is intentional: dpkg reports a
# conflict only when two packages ship the same file, not when they share a
# directory.
function add_config_layout_dirs() {
    add_dir "${OPT_DIR}/conf" 0755
    add_dir "${OPT_DIR}/certs" 0755
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
        # A site-suffixed config package also provides the unsuffixed name, so a
        # generic binary package can depend on one stable name instead of naming
        # a site. The version is included because the binary package pins it.
        if [ -n "${CONFIG_PACKAGE_BASE:-}" ]; then
            echo "Provides: ${CONFIG_PACKAGE_BASE} (= ${CONTROL_VERSION})"
        fi
        if [ -n "${conflicts}" ]; then
            echo "Conflicts: ${conflicts}"
        fi
        echo "Description: ${description}"
        echo " Agent Cluster is a provider-neutral management plane: a Server"
        echo " collects inventory from machine-scoped Endpoints and routes"
        echo " operator commands back to them."
        echo " ."
        echo " This package provides ${ROLE_PHRASE}."
    } >"${PKG_ROOT}/DEBIAN/control" || die "cannot write the control file"
    chmod 0644 "${PKG_ROOT}/DEBIAN/control"
}

# Installs the role configuration as the conffile. The template's relative paths
# are kept unchanged: the packaged controller resolves them against
# /opt/agent-cluster, where conf, certs, data, logs and run are real directories
# beside the controller. One configuration shape therefore serves both the bundle
# and the package, and no absolute override has to be appended.
#
# The conffiles live under /opt/agent-cluster/conf rather than /etc. dpkg honours
# a conffile at any absolute path, so an operator edit still survives an upgrade;
# keeping them beside the controller is what makes the whole product one real
# directory instead of a directory of links into the policy locations.
function write_role_config() {
    local template="$1"
    local config="${OPT_DIR}/conf/node.conf"

    add_file "${template}" "${config}" 0640

    # The endpoint package ships command-allowlist.conf, so the packaged
    # configuration must reference it. A site configuration replaces the template
    # wholesale and may not carry the key, and an empty path makes the Endpoint
    # skip loading the allowlist entirely, which permits every command instead of
    # failing closed. Append the relative path only when the configuration does
    # not already set one, so a site that points elsewhere keeps its own value.
    if [ "${EFFECTIVE_ROLE}" = "endpoint" ]; then
        if ! grep -qE '^[[:space:]]*COMMAND_ALLOWLIST_FILE=' \
            "${PKG_ROOT}${config}"; then
            {
                echo ""
                echo "# The package ships this conffile beside the controller."
                echo "COMMAND_ALLOWLIST_FILE=conf/command-allowlist.conf"
            } >>"${PKG_ROOT}${config}" ||
                die "cannot append the allowlist path"
        fi
        # The control action catalog is the only source of ctl. actions. Without the
        # key the Endpoint advertises no ctl. action, so the packaged configuration
        # must reference the shipped catalog or the feature is silently absent.
        if ! grep -qE '^[[:space:]]*CONTROL_ACTION_FILE=' \
            "${PKG_ROOT}${config}"; then
            {
                echo ""
                echo "# The package ships this conffile beside the controller."
                echo "CONTROL_ACTION_FILE=conf/control-actions.conf"
            } >>"${PKG_ROOT}${config}" ||
                die "cannot append the control action catalog path"
        fi
    fi

    # An adapter override is appended because the last assignment wins and the
    # value must stay single-quoted for the shell that sources it.
    if [ -n "${ADAPTERS}" ]; then
        [ "${EFFECTIVE_ROLE}" = "endpoint" ] || die "--adapters only applies to the endpoint role"
        case "${ADAPTERS}" in
            *"'"*) die "--adapters must not contain a single quote" ;;
        esac
        {
            echo ""
            echo "# Adapter override supplied when the package was built."
            echo "ADAPTERS='${ADAPTERS}'"
        } >>"${PKG_ROOT}${config}" ||
            die "cannot append the adapter override"
    fi

    echo "${config}" >"${PKG_ROOT}/DEBIAN/conffiles" ||
        die "cannot write conffiles"
    # The allowlist is a conffile too: an operator edits it in place, so an upgrade
    # must not silently replace the policy in force with the shipped default.
    if [ "${EFFECTIVE_ROLE}" = "endpoint" ]; then
        echo "${OPT_DIR}/conf/command-allowlist.conf" >>"${PKG_ROOT}/DEBIAN/conffiles" ||
            die "cannot register the allowlist conffile"
        # The catalog is a conffile for the same reason: an operator edits the
        # action surface in place, so an upgrade must not replace it.
        echo "${OPT_DIR}/conf/control-actions.conf" >>"${PKG_ROOT}/DEBIAN/conffiles" ||
            die "cannot register the control action catalog conffile"
    fi
    # The TLS material is a conffile for the same reason, and the consequence of
    # omitting it is worse. A site replaces the shipped development certificate
    # with its own identity, and the certificate subject is what names the node to
    # its peer. Without a conffile entry dpkg overwrites that identity on every
    # upgrade, so the certificate silently reverts to the build host's name while
    # node.conf keeps the site ENDPOINT_ID. The hello identity then disagrees with
    # the certificate and the Server rejects the connection, which looks like a
    # network fault. Registering the material keeps the operator's copy in force
    # and leaves the shipped copy as a .dpkg-dist file to compare against.
    echo "${OPT_DIR}/certs/ca.pem" >>"${PKG_ROOT}/DEBIAN/conffiles" ||
        die "cannot register the CA conffile"
    echo "${OPT_DIR}/certs/node.pem" >>"${PKG_ROOT}/DEBIAN/conffiles" ||
        die "cannot register the certificate conffile"
    echo "${OPT_DIR}/certs/node-key.pem" >>"${PKG_ROOT}/DEBIAN/conffiles" ||
        die "cannot register the private key conffile"
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
        case "${EFFECTIVE_ROLE}" in
            server) CERT="${LOCAL_CERTS}/server.pem" ;;
            endpoint) CERT="${LOCAL_CERTS}/node.pem" ;;
        esac
        [ -n "${CERT}" ] && warn "using the development certificate ${CERT}; pass --cert for a real deployment"
    fi
    if [ -z "${KEY}" ]; then
        case "${EFFECTIVE_ROLE}" in
            server) KEY="${LOCAL_CERTS}/server-key.pem" ;;
            endpoint) KEY="${LOCAL_CERTS}/node-key.pem" ;;
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

# Builds one role package: the binary and its command entry points only.
#
# Configuration and TLS material are shipped by the matching config package, so
# this package is identical on every machine of the same architecture. A site
# identity therefore never enters a binary artifact, and replacing a binary
# cannot overwrite the identity the site installed.
function build_role_package() {
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
    add_layout_dirs
    add_copyright

    # The config package is a hard dependency rather than a recommendation: the
    # daemon cannot start without node.conf and its TLS material, so installing
    # the binary alone would leave a service that fails on every start.
    if [ "${ROLE}" = "endpoint" ]; then
        write_control "agent-cluster-node (= ${CONTROL_VERSION}), agent-cluster-config-endpoint (= ${CONTROL_VERSION}), bash (>= 4.0), coreutils" \
            "agent-cluster-server" \
            "Agent Cluster endpoint daemon and operator CLI"
    else
        write_control "agent-cluster-node (= ${CONTROL_VERSION}), agent-cluster-config-server (= ${CONTROL_VERSION}), bash (>= 4.0), coreutils" \
            "agent-cluster-endpoint" \
            "Agent Cluster server daemon"
    fi
}

# Builds the configuration package for one role: the conffile, the TLS material
# and, for the endpoint role, the allowlist and the control action catalog.
#
# This package carries site data, so it is built per site and is not
# interchangeable between machines. Keeping it separate is what lets the binary
# packages stay generic, and it also keeps a private key out of an artifact that
# is copied to every node.
function build_config_package() {
    local template="${CONFIG}"
    [ -n "${template}" ] ||
        template="${PROJECT_DIR}/conf/node.${EFFECTIVE_ROLE}.conf.example"
    [ -f "${template}" ] || die "missing configuration template ${template}"
    warn_placeholders "${template}"
    resolve_tls

    write_role_config "${template}"
    add_file "${CA}" "${OPT_DIR}/certs/ca.pem" 0644
    add_file "${CERT}" "${OPT_DIR}/certs/node.pem" 0644
    add_file "${KEY}" "${OPT_DIR}/certs/node-key.pem" 0600
    # The endpoint configuration names conf/command-allowlist.conf, which is a real
    # file beside the controller. Without it the Endpoint refuses to start, because
    # a missing allowlist is a configuration error rather than an implicit
    # unrestricted policy.
    if [ "${EFFECTIVE_ROLE}" = "endpoint" ]; then
        add_file "${PROJECT_DIR}/conf/command-allowlist.conf.example" \
            "${OPT_DIR}/conf/command-allowlist.conf" 0640
        # The control action catalog is the only source of ctl. actions. A missing
        # file fails closed by advertising no ctl. action, so the package ships the
        # reviewed catalog to keep the feature available on a fresh install.
        add_file "${PROJECT_DIR}/conf/control-actions.conf.example" \
            "${OPT_DIR}/conf/control-actions.conf" 0640
        # The CLI env file is written from node.conf, so the hook belongs to the
        # package that installs node.conf rather than to the binary package.
        add_file "${SCRIPT_DIR}/deb/postinst.endpoint" "/DEBIAN/postinst" 0755
    fi
    add_config_layout_dirs
    add_copyright

    # Two config packages install the same certificate paths, so they cannot
    # coexist on one machine. Declaring the conflict turns a dpkg file clash into
    # an explicit refusal. The conflict names the unsuffixed virtual package,
    # because every site-suffixed config package provides it, so one entry covers
    # every site without naming any of them.
    if [ "${EFFECTIVE_ROLE}" = "endpoint" ]; then
        write_control "agent-cluster-node (= ${CONTROL_VERSION}), bash (>= 4.0), coreutils" \
            "agent-cluster-config-server" \
            "Agent Cluster endpoint configuration and TLS identity for site ${SITE}"
    else
        write_control "agent-cluster-node (= ${CONTROL_VERSION}), bash (>= 4.0), coreutils" \
            "agent-cluster-config-endpoint" \
            "Agent Cluster server configuration and TLS identity for site ${SITE}"
    fi
}

case "${ROLE}" in
    node) build_node_package ;;
    server | endpoint) build_role_package ;;
    config) build_config_package ;;
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
