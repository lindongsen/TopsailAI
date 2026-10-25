# Test entry points. All test targets launch through uv so the interpreter and
# dependency set come from the project environment instead of the caller shell.
UV ?= uv
PYTHON ?= $(UV) run python

# Resolve roots from this Makefile's location so results do not depend on the
# caller's working directory.
MAKEFILE_DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
PROJECT_ROOT := $(patsubst %/,%,$(MAKEFILE_DIR))
SRC_ROOT := $(abspath $(PROJECT_ROOT)/..)
CLI_ROOT := $(PROJECT_ROOT)/cli

# Core tests import both the project package and the CLI package, so the CLI
# root is required. Order matters: the project root must precede the CLI root
# because cli/ai_team.py would otherwise shadow the ai_team package.
CORE_PYTHONPATH := $(PROJECT_ROOT):$(SRC_ROOT):$(CLI_ROOT)
# CLI tests use pytest_plugins with the top-level name "tests", which must
# resolve to cli/tests. Adding the project root here would shadow it.
CLI_PYTHONPATH := $(CLI_ROOT)

PYTEST_FLAGS := -q --color=no --tb=line --disable-warnings

.PHONY: help test test-unit test-bdd test-bdd-slow core-unit-test core-bdd-test core-bdd-slow cli-unit-test cli-bdd-test

help:
	@printf '%s\n' \
		'Available targets:' \
		'  help            Show this help message' \
		'  test            Run all tests (core + CLI, unit + BDD)' \
		'  test-unit       Run core and CLI unit tests' \
		'  test-bdd        Run core and CLI BDD tests' \
		'  test-bdd-slow   Run core and CLI slow BDD acceptance tests' \
		'  core-unit-test  Run core unit tests' \
		'  core-bdd-test   Run core BDD tests' \
		'  core-bdd-slow   Run core slow BDD acceptance tests' \
		'  cli-unit-test   Run CLI unit tests' \
		'  cli-bdd-test    Run CLI BDD tests' \
		'' \
		'All test targets run through uv with an explicit PYTHONPATH.'

test: test-unit test-bdd

test-unit: core-unit-test cli-unit-test

test-bdd: core-bdd-test cli-bdd-test

test-bdd-slow: core-bdd-slow

core-unit-test:
	cd $(PROJECT_ROOT) && PYTHONPATH=$(CORE_PYTHONPATH) $(PYTHON) tests/run_tests.py

core-bdd-test:
	cd $(PROJECT_ROOT) && PYTHONPATH=$(CORE_PYTHONPATH) $(PYTHON) -B -m pytest $(PYTEST_FLAGS) -m "not slow" tests/bdd

core-bdd-slow:
	cd $(PROJECT_ROOT) && PYTHONPATH=$(CORE_PYTHONPATH) $(PYTHON) -B -m pytest $(PYTEST_FLAGS) -m "slow" tests/bdd

cli-unit-test:
	cd $(CLI_ROOT) && PYTHONPATH=$(CLI_PYTHONPATH) $(PYTHON) -B -m pytest $(PYTEST_FLAGS) tests/unit

cli-bdd-test:
	cd $(CLI_ROOT) && PYTHONPATH=$(CLI_PYTHONPATH) $(PYTHON) -B -m pytest $(PYTEST_FLAGS) tests/bdd
