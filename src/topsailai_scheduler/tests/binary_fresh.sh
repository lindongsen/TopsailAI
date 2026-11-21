#!/usr/bin/env bash
# binary_fresh.sh reports whether the scheduler binary is built from the current sources.
#
# A live or BDD suite that runs a stale binary reports a green result for code
# that is not under test. That happened once: the binary was built at 04:26,
# the reconciliation sources changed at 05:08, and the live suite passed while
# exercising a binary that contained none of the new code. `make check` runs
# `go test`, not `make build`, so nothing caught it.
#
# Exit 0 when the binary exists and is at least as new as every source file.
# Exit 1 when it is missing or stale, printing the offending files on stderr.

set -u

# PROJECT_ROOT is the repository root, derived from this file's location.
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# BINARY is the scheduler built by the Makefile.
BINARY="${PROJECT_ROOT}/.tmp/topsailai_scheduler"
# SOURCE_DIR holds every file the binary is compiled from.
SOURCE_DIR="${PROJECT_ROOT}/src"

if [ ! -x "${BINARY}" ]; then
	printf 'binary %s is missing; run make build first\n' "${BINARY}" >&2
	exit 1
fi

# newer collects every source file the binary does not cover.
newer="$(find "${SOURCE_DIR}" -name '*.go' -newer "${BINARY}" -print 2>/dev/null)"
# The module files change the build just as source files do.
for extra in "${SOURCE_DIR}/go.mod" "${SOURCE_DIR}/go.sum"; do
	if [ -f "${extra}" ] && [ "${extra}" -nt "${BINARY}" ]; then
		newer="${newer}${newer:+
}${extra}"
	fi
done

if [ -n "${newer}" ]; then
	printf 'binary %s is older than these sources; run make build first:\n%s\n' \
		"${BINARY}" "${newer}" >&2
	exit 1
fi

exit 0
