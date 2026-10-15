#!/bin/sh
# Send one message to a running TopsailAI CLI through its session input pipe.
#
# This script only writes input; it never starts the program, asserts output,
# or performs cleanup.
#
# Usage: interact_two_layer_cli.sh <run-dir> <mode> <command>
#   mode: multiline | single
#     multiline -> "<command>\nEOF\n" (EOF terminates the message)
#     single    -> "<command>\n"     (Enter only; no EOF terminator)
set -eu

run_dir=$1
mode=$2
command=$3

pipe=$(find "$run_dir/home/.topsailai/workspace/task" -type p -name '*.session.pipe' 2>/dev/null | head -1 || true)
if [ -z "$pipe" ]; then
  echo "session input pipe not found under $run_dir" >&2
  exit 1
fi

if [ "$mode" = multiline ]; then
  printf '%s\nEOF\n' "$command" > "$pipe"
else
  printf '%s\n' "$command" > "$pipe"
fi
