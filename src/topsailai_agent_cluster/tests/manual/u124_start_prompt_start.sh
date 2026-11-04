#!/usr/bin/env bash
set -euo pipefail
EXE_FILE=$(readlink -f "$0")
EXE_FOLDER=$(dirname "${EXE_FILE}")
cd "${EXE_FOLDER}" || exit 1
if [[ ${1:-} == --help || ${1:-} == -h ]]; then
    printf '%s\n' 'Build and run the real stdin terminal harness only' 'Usage: ARTIFACT_DIR=/absolute/tmp UNIT_C_TERMINAL_CASE=complete u124_start_prompt_start.sh' 'Exit: child status or 2 for invalid configuration'
    exit 0
fi
WORKSPACE=$(cd "${EXE_FOLDER}/../.." && pwd)
DIR=${ARTIFACT_DIR:?absolute case artifact directory required}
CASE=${UNIT_C_TERMINAL_CASE:?terminal case required}
case "$DIR" in "$WORKSPACE"/.tmp/u124/unit-c/implementation/*) ;; *) echo 'artifact path outside task evidence' >&2; exit 2;; esac
mkdir -p "$DIR/cache" "$DIR/gotmp"
export NO_COLOR=1 TERM=dumb GOCACHE="$WORKSPACE/.tmp/u124/unit-c/implementation/c17/cache" GOTMPDIR="$DIR/gotmp" TMPDIR="$DIR/gotmp"
# A fresh compile must succeed; never run a stale binary after compilation failure.
if go test -c -o "$DIR/terminal.test" "$WORKSPACE/internal/tui" >"$DIR/build-output.txt" 2>&1; then
    printf 'tty=%s\n' "$(tty)" >"$DIR/terminal-fds.txt"
    ps -o pid,ppid,sid,pgid,tpgid,tty,stat -p $$ >>"$DIR/terminal-fds.txt"
    if UNIT_C_TERMINAL=1 UNIT_C_TERMINAL_DIR="$DIR" UNIT_C_TERMINAL_CASE="$CASE" "$DIR/terminal.test" -test.run '^TestUnitCStartPromptTerminalHarness$' -test.count=1 -test.v; then STATUS=0; else STATUS=$?; fi
else STATUS=$?; fi
printf '%s\n' "$STATUS" >"$DIR/start-exit-status.txt.tmp"
mv "$DIR/start-exit-status.txt.tmp" "$DIR/start-exit-status.txt"
exit "$STATUS"
