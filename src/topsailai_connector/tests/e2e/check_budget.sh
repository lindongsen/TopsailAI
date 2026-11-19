#!/usr/bin/env bash
# Author: DawsonLin
# Purpose: Decide whether a measurement report is within the recorded budget.
#
# `measure_read.sh` measures and reports; it deliberately does not judge, because a
# threshold with no baseline is a guess with a test around it. This script is the
# other half: it reads the report and compares it with the rule written in
# `docs/resource-baseline.md`. The two must not drift, so every threshold below
# names the row of that document it implements.
#
# The rule is expressed as ratios and bounded properties, not as absolute numbers.
# The host is shared, and two runs of one binary differed by 2.3x in throughput, so
# an absolute figure is a record of one host at one time. A ratio change is a code
# change; an absolute change with a stable ratio is host load.
#
# Absolute CPU is therefore reported as INCONCLUSIVE when the host load differs
# from the baseline run's load by more than the documented margin. Failing a
# correct build because someone else's process was running teaches the operator to
# ignore this check, and the next real regression is then ignored too.
#
# Usage:
#   tests/e2e/check_budget.sh [REPORT]
#
# Exit status is 0 when no rule failed, 1 when any rule failed. INCONCLUSIVE is not
# a failure: it means the number cannot be compared, which is different from a
# number that is wrong.

set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
REPORT=${1:-"$ROOT/.tmp/e2e/measure-report.txt"}

# Thresholds, each naming the row of docs/resource-baseline.md it implements.
#
# RSS_GROWTH_FRACTION is the share of the idle baseline that peak RSS may grow by
# between the small and the large size. A proportional increase means the chunk
# pipeline was replaced by a whole-file buffer, which is the defect this rule
# exists to catch.
RSS_GROWTH_FRACTION=0.25
# The CPU rule has two parts, and they are deliberately not the same verdict.
#
# SERVER_CPU_BASELINE_PER_MIB and NODE_CPU_BASELINE_PER_MIB are the measured cost at
# the recorded revision, taken from docs/resource-baseline.md. A regression is a
# rise above the baseline by REGRESSION_FACTOR, and that is what fails this check.
#
# SERVER_CPU_TARGET_PER_16MIB and NODE_CPU_TARGET_PER_16MIB are the PRD budgets. The
# recorded baseline already exceeds both: 0.038 s/MiB is 0.61 s/16MiB against a
# 0.25 budget, and 0.011 s/MiB is 0.18 s/16MiB against a 0.10 budget. A gate the
# current build cannot pass is a gate nobody will respect, so an unmet target is
# reported as TARGET-MISSED and does not fail the run. It is still printed on every
# run, because a target that stops being mentioned is a target that was abandoned
# without a decision. Closing the gap is Unit 4a's job, not this check's.
SERVER_CPU_BASELINE_PER_MIB=0.038
NODE_CPU_BASELINE_PER_MIB=0.011
SERVER_CPU_TARGET_PER_16MIB=0.25
NODE_CPU_TARGET_PER_16MIB=0.10
REGRESSION_FACTOR=1.25
# NODE_WIRE_CEILING is the PRD target on the hop where the binary transport works.
NODE_WIRE_CEILING=1.10
# SERVER_WIRE_CEILING is the current known state, not a target: the Server still
# re-encodes content as base64 JSON before writing the HTTP response. A rise above
# this is a regression today; a fall is the improvement Unit 4a is meant to deliver.
SERVER_WIRE_CEILING=1.3371
# RATIO_TOLERANCE absorbs four-decimal rounding in the report. It is not slack: the
# ratio is stable to four decimals across a 64x size range, so a real change is far
# larger than this.
RATIO_TOLERANCE=0.005
# LOAD_MARGIN is the documented margin for comparing absolute CPU. The baseline was
# recorded with /proc/loadavg between 2.06 and 3.91.
BASELINE_LOAD_MAX=3.91
LOAD_MARGIN=1.0
# The two sizes the bounded-memory rule compares. The rule is a comparison between
# sizes, so both must be present or the rule cannot be evaluated.
SMALL_MIB=16
LARGE_MIB=64

fail() {
	echo "budget: $*" >&2
	exit 1
}

[ -f "$REPORT" ] || fail "$REPORT is missing; run 'make measure' first"

failures=0
inconclusive=0

# pass, bad and skip print one verdict line and keep the counters.
pass() {
	printf 'PASS          %-34s %s\n' "$1" "$2"
}

bad() {
	printf 'FAIL          %-34s %s\n' "$1" "$2"
	failures=$((failures + 1))
}

skip() {
	printf 'INCONCLUSIVE  %-34s %s\n' "$1" "$2"
	inconclusive=$((inconclusive + 1))
}

# field prints one key's value from the block for one size.
#
# The report is a sequence of blank-line-separated blocks, each starting with
# `platform=`. Selecting by `size_bytes` rather than by block order means a report
# with an extra size, or with the sizes in another order, still evaluates correctly.
field() {
	local size_mib=$1 key=$2
	awk -v want="$((size_mib * 1024 * 1024))" -v key="$key" '
		BEGIN { RS = ""; FS = "\n" }
		{
			size = ""
			value = ""
			for (i = 1; i <= NF; i++) {
				if ($i ~ /^size_bytes=/) { size = substr($i, 12) }
				if (index($i, key "=") == 1) { value = substr($i, length(key) + 2) }
			}
			if (size == want && value != "") { print value; exit }
		}
	' "$REPORT"
}

# sizes prints every size in the report, in MiB, ascending.
sizes() {
	awk -F= '/^size_bytes=/ { printf "%d\n", $2 / 1048576 }' "$REPORT" | sort -n | uniq
}

# at_least reports whether a is greater than b, using awk so a decimal comparison
# does not depend on the shell.
greater_than() {
	awk -v a="$1" -v b="$2" 'BEGIN { exit !(a > b) }'
}

# cpu_per_16mib converts a total CPU time and a size into CPU-seconds per 16 MiB.
cpu_per_16mib() {
	awk -v cpu="$1" -v bytes="$2" 'BEGIN { printf "%.4f", cpu / (bytes / 16777216) }'
}

echo "budget: report $REPORT"
echo "budget: host load $(cut -d' ' -f1-3 /proc/loadavg 2>/dev/null || echo unknown)"
echo

# Rule: content identity. A fast wrong answer is not an improvement, so this is
# checked first and for every size.
for size in $(sizes); do
	verified=$(field "$size" content_verified)
	if [ "$verified" = "yes" ]; then
		pass "content identity ${size} MiB" "byte-identical"
	else
		bad "content identity ${size} MiB" "content_verified=${verified:-missing}"
	fi
done

# Rule: Node wire ratio, the PRD target on the hop where the binary transport works.
for size in $(sizes); do
	ratio=$(field "$size" node_wire_ratio)
	[ -n "$ratio" ] || {
		bad "node wire ratio ${size} MiB" "missing from report"
		continue
	}
	ceiling=$(awk -v c="$NODE_WIRE_CEILING" -v t="$RATIO_TOLERANCE" 'BEGIN { printf "%.4f", c + t }')
	if greater_than "$ratio" "$ceiling"; then
		bad "node wire ratio ${size} MiB" "$ratio > $NODE_WIRE_CEILING"
	else
		pass "node wire ratio ${size} MiB" "$ratio <= $NODE_WIRE_CEILING"
	fi
done

# Rule: Server wire ratio, recorded as the current known state rather than a target.
for size in $(sizes); do
	ratio=$(field "$size" server_wire_ratio)
	[ -n "$ratio" ] || {
		bad "server wire ratio ${size} MiB" "missing from report"
		continue
	}
	ceiling=$(awk -v c="$SERVER_WIRE_CEILING" -v t="$RATIO_TOLERANCE" 'BEGIN { printf "%.4f", c + t }')
	if greater_than "$ratio" "$ceiling"; then
		bad "server wire ratio ${size} MiB" "$ratio > $SERVER_WIRE_CEILING (base64 hop)"
	else
		pass "server wire ratio ${size} MiB" "$ratio <= $SERVER_WIRE_CEILING"
	fi
done

# Rule: bounded memory. Peak RSS must not grow proportionally with the file. VmHWM
# is cumulative, so the growth between two sizes is the difference of the two
# high-water marks, and the threshold is a share of the idle baseline.
small_server=$(field "$SMALL_MIB" server_peak_rss_kb)
large_server=$(field "$LARGE_MIB" server_peak_rss_kb)
small_node=$(field "$SMALL_MIB" node_peak_rss_kb)
large_node=$(field "$LARGE_MIB" node_peak_rss_kb)
server_idle=$(field "$SMALL_MIB" server_rss_baseline_kb)
node_idle=$(field "$SMALL_MIB" node_rss_baseline_kb)

if [ -z "$small_server" ] || [ -z "$large_server" ] || [ -z "$server_idle" ]; then
	skip "server peak RSS growth" "needs ${SMALL_MIB} and ${LARGE_MIB} MiB blocks"
else
	growth=$((large_server - small_server))
	allowed=$(awk -v i="$server_idle" -v f="$RSS_GROWTH_FRACTION" 'BEGIN { printf "%d", i * f }')
	if [ "$growth" -gt "$allowed" ]; then
		bad "server peak RSS growth" "+${growth} KB > ${allowed} KB (25% of ${server_idle} KB idle)"
	else
		pass "server peak RSS growth" "+${growth} KB <= ${allowed} KB (25% of ${server_idle} KB idle)"
	fi
fi

if [ -z "$small_node" ] || [ -z "$large_node" ] || [ -z "$node_idle" ]; then
	skip "node peak RSS growth" "needs ${SMALL_MIB} and ${LARGE_MIB} MiB blocks"
else
	growth=$((large_node - small_node))
	allowed=$(awk -v i="$node_idle" -v f="$RSS_GROWTH_FRACTION" 'BEGIN { printf "%d", i * f }')
	if [ "$growth" -gt "$allowed" ]; then
		bad "node peak RSS growth" "+${growth} KB > ${allowed} KB (25% of ${node_idle} KB idle)"
	else
		pass "node peak RSS growth" "+${growth} KB <= ${allowed} KB (25% of ${node_idle} KB idle)"
	fi
fi

# Rule: CPU per 16 MiB, in two verdicts.
#
# The regression verdict compares against the measured baseline and fails the run.
# The target verdict compares against the PRD budget and only reports, because the
# baseline already exceeds that budget and a gate the current build cannot pass is a
# gate nobody will respect.
#
# Absolute CPU is comparable only when the host load is close to the baseline run's,
# so a busy host yields INCONCLUSIVE rather than a failure. Failing a correct build
# because someone else's process was running teaches the operator to ignore this
# check, and the next real regression is then ignored too.
current_load=$(cut -d' ' -f1 /proc/loadavg 2>/dev/null || echo "")
load_ceiling=$(awk -v b="$BASELINE_LOAD_MAX" -v m="$LOAD_MARGIN" 'BEGIN { printf "%.2f", b + m }')
load_comparable=1
if [ -z "$current_load" ]; then
	load_comparable=0
elif greater_than "$current_load" "$load_ceiling"; then
	load_comparable=0
fi

for size in $(sizes); do
	bytes=$(field "$size" size_bytes)
	server_cpu=$(field "$size" server_cpu_seconds)
	node_cpu=$(field "$size" node_cpu_seconds)
	if [ -z "$bytes" ] || [ -z "$server_cpu" ] || [ -z "$node_cpu" ]; then
		bad "cpu ${size} MiB" "missing from report"
		continue
	fi
	server_rate=$(cpu_per_16mib "$server_cpu" "$bytes")
	node_rate=$(cpu_per_16mib "$node_cpu" "$bytes")
	if [ "$load_comparable" -eq 0 ]; then
		skip "server cpu ${size} MiB" "${server_rate} s/16MiB, load ${current_load:-unknown} > ${load_ceiling}"
		skip "node cpu ${size} MiB" "${node_rate} s/16MiB, load ${current_load:-unknown} > ${load_ceiling}"
		continue
	fi

	# Regression verdict: a rise above the measured baseline by REGRESSION_FACTOR.
	server_regression=$(awk -v b="$SERVER_CPU_BASELINE_PER_MIB" -v f="$REGRESSION_FACTOR" \
		'BEGIN { printf "%.4f", b * f * 16 }')
	node_regression=$(awk -v b="$NODE_CPU_BASELINE_PER_MIB" -v f="$REGRESSION_FACTOR" \
		'BEGIN { printf "%.4f", b * f * 16 }')
	if greater_than "$server_rate" "$server_regression"; then
		bad "server cpu regression ${size} MiB" "${server_rate} s/16MiB > ${server_regression} (baseline x${REGRESSION_FACTOR})"
	else
		pass "server cpu regression ${size} MiB" "${server_rate} s/16MiB <= ${server_regression}"
	fi
	if greater_than "$node_rate" "$node_regression"; then
		bad "node cpu regression ${size} MiB" "${node_rate} s/16MiB > ${node_regression} (baseline x${REGRESSION_FACTOR})"
	else
		pass "node cpu regression ${size} MiB" "${node_rate} s/16MiB <= ${node_regression}"
	fi

	# Target verdict: the PRD budget. Reported, never fatal, because the baseline
	# already exceeds it and the gap is Unit 4a's work.
	if greater_than "$server_rate" "$SERVER_CPU_TARGET_PER_16MIB"; then
		printf 'TARGET-MISSED %-34s %s\n' "server cpu target ${size} MiB" \
			"${server_rate} s/16MiB > ${SERVER_CPU_TARGET_PER_16MIB} PRD budget"
	else
		pass "server cpu target ${size} MiB" "${server_rate} s/16MiB <= ${SERVER_CPU_TARGET_PER_16MIB}"
	fi
	if greater_than "$node_rate" "$NODE_CPU_TARGET_PER_16MIB"; then
		printf 'TARGET-MISSED %-34s %s\n' "node cpu target ${size} MiB" \
			"${node_rate} s/16MiB > ${NODE_CPU_TARGET_PER_16MIB} PRD budget"
	else
		pass "node cpu target ${size} MiB" "${node_rate} s/16MiB <= ${NODE_CPU_TARGET_PER_16MIB}"
	fi
done

echo
if [ "$failures" -gt 0 ]; then
	echo "budget: $failures rule(s) failed, $inconclusive inconclusive" >&2
	exit 1
fi
echo "budget: no rule failed, $inconclusive inconclusive"
