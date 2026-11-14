# Test entry points. All test targets launch through uv so the interpreter and
# dependency set come from the project environment instead of the caller shell.
UV ?= uv
# Tests must always run through uv so the interpreter and dependency set come
# from the project environment. `:=` (not `?=`) is deliberate: an exported
# PYTHON in the caller shell would otherwise silently replace uv with a bare
# interpreter. A command-line override (make PYTHON=...) still wins.
PYTHON := $(UV) run python

# Resolve roots from this Makefile's location so results do not depend on the
# caller's working directory.
MAKEFILE_DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
PROJECT_ROOT := $(patsubst %/,%,$(MAKEFILE_DIR))
SRC_ROOT := $(abspath $(PROJECT_ROOT)/..)
CLI_ROOT := $(PROJECT_ROOT)/cli
REPOSITORY_ROOT := $(abspath $(SRC_ROOT)/..)
DEB_OUTPUT_DIR := $(REPOSITORY_ROOT)/build/output
PACKAGED_TEST_TMP := $(PROJECT_ROOT)/.tmp/packaged-bdd

# Core tests import both the project package and the CLI package, so the CLI
# root is required. Order matters: the project root must precede the CLI root
# because cli/ai_team.py would otherwise shadow the ai_team package.
CORE_PYTHONPATH := $(PROJECT_ROOT):$(SRC_ROOT):$(CLI_ROOT)
# CLI tests use pytest_plugins with the top-level name "tests", which must
# resolve to cli/tests. Adding the project root here would shadow it.
CLI_PYTHONPATH := $(CLI_ROOT)

PYTEST_FLAGS := -q --color=no --tb=line --disable-warnings

# Every test target tees its output to a timestamped log under .tmp so a run can
# be inspected after the terminal has scrolled away. .tmp is git-ignored.
# pipefail is required: without it the pipeline exit status is tee's, so a
# failing test suite would still make the target succeed.
SHELL := /bin/bash
LOG_DIR := $(PROJECT_ROOT)/.tmp/test-logs
LOG_TS := $(shell date +%Y%m%dT%H%M%S)
# Keep only the most recent logs so .tmp cannot grow without bound.
LOG_KEEP_COUNT ?= 50

.PHONY: help test-log-init test test-unit test-bdd test-bdd-slow test-bdd-packaged test-release core-unit-test core-bdd-test core-bdd-slow cli-unit-test cli-bdd-test

help:
	@printf '%s\n' \
		'Available targets:' \
		'  help            Show this help message' \
		'  test            Run source tests (core + CLI + plugins, unit + BDD)' \
		'  test-unit       Run core CLI and plugin unit tests' \
		'  test-bdd        Run core CLI and plugin BDD tests' \
		'  test-bdd-slow   Run core and CLI slow BDD acceptance tests' \
		'  core-unit-test  Run core unit tests' \
		'  test-bdd-packaged Build standard DEBs then test their staging tree' \
		'  test-release    Require source slow and packaged test gates' \
		'  core-bdd-test   Run core source BDD tests' \
		'  core-bdd-slow   Run core slow BDD acceptance tests' \
		'  cli-unit-test   Run CLI unit tests' \
		'  cli-bdd-test    Run CLI BDD tests' \
		'  plugins-test    Run independent plugin unit and BDD tests' \
		'' \
		'All test targets run through uv with an explicit PYTHONPATH.' \
		'Every test target prints its log path and tees output to:' \
		'  $(LOG_DIR)/<target>_<timestamp>.log' \
		'Override the retained log count with LOG_KEEP_COUNT (default: $(LOG_KEEP_COUNT)).'

# Create the log directory and prune old logs before a test target writes one.
# Phony, so it runs once per make invocation and always prunes before writing.
test-log-init:
	@mkdir -p "$(LOG_DIR)"
	@ls -1t "$(LOG_DIR)"/*.log 2>/dev/null | tail -n +$$(( $(LOG_KEEP_COUNT) + 1 )) | while read -r old; do \
		echo "==> Pruning old log: $$old"; \
		rm -f "$$old"; \
	done

test: test-unit test-bdd

test-unit: core-unit-test cli-unit-test plugins-unit-test

test-bdd: core-bdd-test cli-bdd-test plugins-bdd-test

test-bdd-slow: core-bdd-slow

test-release: test test-bdd-slow test-bdd-packaged

test-bdd-packaged: test-log-init
	@LOG_FILE="$(LOG_DIR)/test-bdd-packaged_$(LOG_TS).log"; \
	echo "==> Log: $$LOG_FILE"; \
	set -o pipefail; \
	{ \
		$(MAKE) -C "$(REPOSITORY_ROOT)" build-deb && \
		mkdir -p "$(PACKAGED_TEST_TMP)" && \
		cd "$(PROJECT_ROOT)" && TOPSAILAI_PACKAGED_ROOT="$(DEB_OUTPUT_DIR)/.deb/topsailai/TopsailAI/src" PYTHONDONTWRITEBYTECODE=1 TMPDIR="$(PACKAGED_TEST_TMP)" PYTHONPATH=$(CORE_PYTHONPATH) $(PYTHON) -B -m pytest $(PYTEST_FLAGS) --basetemp="$(PACKAGED_TEST_TMP)/pytest" -o cache_dir="$(PACKAGED_TEST_TMP)/cache" -m "packaged" tests/bdd ; \
	} 2>&1 | tee "$$LOG_FILE"; \
	status=$$?; \
	echo "==> Log saved: $$LOG_FILE"; \
	exit $$status

core-unit-test: test-log-init
	@LOG_FILE="$(LOG_DIR)/core-unit-test_$(LOG_TS).log"; \
	echo "==> Log: $$LOG_FILE"; \
	set -o pipefail; \
	{ cd $(PROJECT_ROOT) && PYTHONPATH=$(CORE_PYTHONPATH) $(PYTHON) tests/run_tests.py ; } 2>&1 | tee "$$LOG_FILE"; \
	status=$$?; \
	echo "==> Log saved: $$LOG_FILE"; \
	exit $$status

core-bdd-test: test-log-init
	@LOG_FILE="$(LOG_DIR)/core-bdd-test_$(LOG_TS).log"; \
	echo "==> Log: $$LOG_FILE"; \
	set -o pipefail; \
	{ cd $(PROJECT_ROOT) && PYTHONPATH=$(CORE_PYTHONPATH) $(PYTHON) -B -m pytest $(PYTEST_FLAGS) -m "not slow and not packaged" tests/bdd ; } 2>&1 | tee "$$LOG_FILE"; \
	status=$$?; \
	echo "==> Log saved: $$LOG_FILE"; \
	exit $$status

core-bdd-slow: test-log-init
	@LOG_FILE="$(LOG_DIR)/core-bdd-slow_$(LOG_TS).log"; \
	echo "==> Log: $$LOG_FILE"; \
	set -o pipefail; \
	{ cd $(PROJECT_ROOT) && PYTHONPATH=$(CORE_PYTHONPATH) $(PYTHON) -B -m pytest $(PYTEST_FLAGS) -m "slow" tests/bdd ; } 2>&1 | tee "$$LOG_FILE"; \
	status=$$?; \
	echo "==> Log saved: $$LOG_FILE"; \
	exit $$status

cli-unit-test: test-log-init
	@LOG_FILE="$(LOG_DIR)/cli-unit-test_$(LOG_TS).log"; \
	echo "==> Log: $$LOG_FILE"; \
	set -o pipefail; \
	{ cd $(CLI_ROOT) && PYTHONPATH=$(CLI_PYTHONPATH) $(PYTHON) -B -m pytest $(PYTEST_FLAGS) tests/unit ; } 2>&1 | tee "$$LOG_FILE"; \
	status=$$?; \
	echo "==> Log saved: $$LOG_FILE"; \
	exit $$status

cli-bdd-test: test-log-init
	@LOG_FILE="$(LOG_DIR)/cli-bdd-test_$(LOG_TS).log"; \
	echo "==> Log: $$LOG_FILE"; \
	set -o pipefail; \
	{ cd $(CLI_ROOT) && PYTHONPATH=$(CLI_PYTHONPATH) $(PYTHON) -B -m pytest $(PYTEST_FLAGS) tests/bdd ; } 2>&1 | tee "$$LOG_FILE"; \
	status=$$?; \
	echo "==> Log saved: $$LOG_FILE"; \
	exit $$status

.PHONY: plugins-test plugins-unit-test plugins-bdd-test
plugins-test: test-log-init
	@LOG_FILE="$(LOG_DIR)/plugins-test_$(LOG_TS).log"; \
	echo "==> Log: $$LOG_FILE"; \
	set -o pipefail; \
	{ $(MAKE) -C $(PROJECT_ROOT)/plugins test ; } 2>&1 | tee "$$LOG_FILE"; \
	status=$$?; \
	echo "==> Log saved: $$LOG_FILE"; \
	exit $$status

plugins-unit-test: test-log-init
	@LOG_FILE="$(LOG_DIR)/plugins-unit-test_$(LOG_TS).log"; \
	echo "==> Log: $$LOG_FILE"; \
	set -o pipefail; \
	{ $(MAKE) -C $(PROJECT_ROOT)/plugins test-unit ; } 2>&1 | tee "$$LOG_FILE"; \
	status=$$?; \
	echo "==> Log saved: $$LOG_FILE"; \
	exit $$status

plugins-bdd-test: test-log-init
	@LOG_FILE="$(LOG_DIR)/plugins-bdd-test_$(LOG_TS).log"; \
	echo "==> Log: $$LOG_FILE"; \
	set -o pipefail; \
	{ $(MAKE) -C $(PROJECT_ROOT)/plugins test-bdd ; } 2>&1 | tee "$$LOG_FILE"; \
	status=$$?; \
	echo "==> Log saved: $$LOG_FILE"; \
	exit $$status
