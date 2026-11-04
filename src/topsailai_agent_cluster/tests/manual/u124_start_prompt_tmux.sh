#!/usr/bin/env bash
set -euo pipefail
EXE_FILE=$(readlink -f "$0")
EXE_FOLDER=$(dirname "${EXE_FILE}")
cd "${EXE_FOLDER}" || exit 1
if [[ ${1:-} == --help || ${1:-} == -h ]]; then
    printf '%s\n' 'Drive isolated real tmux PTY cases and verify child evidence' 'Usage: u124_start_prompt_tmux.sh [complete|help-invalid|cancel|quit|refresh|command-interrupt|numeric-literal|residual-half-line ...]' 'No arguments runs all cases; exit 0 success 1 assertion failure 2 configuration failure'
    exit 0
fi
WORKSPACE=$(cd "${EXE_FOLDER}/../.." && pwd)
ROOT=${ARTIFACT_DIR:-"$WORKSPACE/.tmp/u124/unit-c/implementation/batch3/terminal/run-$(date +%Y%m%dT%H%M%S)-$$"}
case "$ROOT" in "$WORKSPACE"/.tmp/u124/unit-c/implementation/*) ;; *) echo 'artifact path outside task evidence' >&2; exit 2;; esac
mkdir -p "$ROOT"
if [[ $# == 0 ]]; then set -- complete help-invalid cancel quit refresh command-interrupt numeric-literal residual-half-line; fi
OWNED=0
cleanup() {
    if [[ $OWNED == 1 ]]; then
        tmux -S "$SOCKET" capture-pane -p -S - -t owned >"$DIR/pane.txt" 2>/dev/null || true
        tmux -S "$SOCKET" kill-session -t owned
        printf 'deleted owned session socket=%s\n' "$SOCKET" >>"$ROOT/cleanup.log"
        OWNED=0
    fi
}
trap cleanup EXIT
trap 'exit 130' INT TERM
for CASE in "$@"; do
    case "$CASE" in complete|help-invalid|cancel|quit|refresh|command-interrupt|numeric-literal|residual-half-line) ;; *) echo "unknown case $CASE" >&2; exit 2;; esac
    DIR="$ROOT/$CASE"
    if [[ -e "$DIR" ]]; then echo "refusing reused evidence $DIR" >&2; exit 2; fi
    mkdir -p "$DIR"
    # The short socket path remains within task temporary storage; one server per case.
    SOCKET="$WORKSPACE/.tmp/u124/f5-$$-$CASE.sock"
    tmux -S "$SOCKET" new-session -d -s owned -x 160 -y 45
    OWNED=1
    tmux -S "$SOCKET" set-option -t owned remain-on-exit on
    printf -v LAUNCH 'ARTIFACT_DIR=%q UNIT_C_TERMINAL_CASE=%q %q' "$DIR" "$CASE" "$EXE_FOLDER/u124_start_prompt_start.sh"
    tmux -S "$SOCKET" send-keys -t owned -l -- "$LAUNCH"
    tmux -S "$SOCKET" send-keys -t owned Enter
    wait_ready() {
        local ORDINAL=$1 FIELD=$2
        for ((I=0; I<1800; I++)); do
            if [[ -s "$DIR/readiness.json" ]] && python3 -c 'import json,sys; d=json.load(open(sys.argv[1]));sys.exit(not(d["case"]==sys.argv[2] and d["ordinal"]==int(sys.argv[3]) and d["field"]==sys.argv[4]))' "$DIR/readiness.json" "$CASE" "$ORDINAL" "$FIELD"; then return; fi
            if [[ -f "$DIR/start-exit-status.txt" ]]; then echo "early exit $CASE $ORDINAL/$FIELD" >&2; return 1; fi
            sleep 0.1
        done
        echo "readiness timeout $CASE $ORDINAL/$FIELD" >&2; return 1
    }
    answer() { tmux -S "$SOCKET" send-keys -t owned -l -- "$1"; tmux -S "$SOCKET" send-keys -t owned Enter; }
    wait_ready 1 main; answer start; wait_ready 2 endpoint
    ORD=2
    case "$CASE" in
        cancel) answer cancel; wait_ready 3 main; answer quit;;
        quit) answer q;;
        refresh) answer r; wait_ready 3 main; answer quit;;
        command-interrupt|residual-half-line)
            if [[ "$CASE" == residual-half-line ]]; then tmux -S "$SOCKET" send-keys -t owned -l -- partial-answer; fi
            tmux -S "$SOCKET" send-keys -t owned C-c
            wait_ready 3 main; answer quit;;
        *)
            if [[ "$CASE" == help-invalid ]]; then
                answer help; wait_ready 3 endpoint
                answer 'two values'; wait_ready 4 endpoint
                ORD=4
            fi
            VALUES=(endpoint-1 resource-1 profile-1 revision-1)
            if [[ "$CASE" == numeric-literal ]]; then VALUES=(1 2 3 4); fi
            FIELDS=(resource profile profile-revision main)
            for INDEX in 0 1 2 3; do answer "${VALUES[$INDEX]}"; ORD=$((ORD+1)); wait_ready "$ORD" "${FIELDS[$INDEX]}"; done
            answer quit;;
    esac
    for ((I=0; I<600; I++)); do [[ -f "$DIR/start-exit-status.txt" ]] && break; sleep 0.1; done
    [[ $(cat "$DIR/start-exit-status.txt") == 0 ]]
    python3 -c 'import json,sys;d=json.load(open(sys.argv[1]+"/terminal-result.json"));assert d["case"]==sys.argv[2] and d["status"]=="PASS"' "$DIR" "$CASE"
    ! tmux -S "$SOCKET" capture-pane -p -S - -t owned | grep -q -- '--- SKIP:'
    cleanup
    printf 'PASS %s\n' "$CASE"
done
printf 'evidence=%s\n' "$ROOT"
