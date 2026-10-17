PYTHON ?= python
PYTEST ?= pytest

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
		'  cli-bdd-test    Run CLI BDD tests'

test: test-unit test-bdd

test-unit: core-unit-test cli-unit-test

test-bdd: core-bdd-test cli-bdd-test

test-bdd-slow: core-bdd-slow

core-unit-test:
	$(PYTHON) tests/run_tests.py

core-bdd-test:
	$(PYTEST) -q --color=no --tb=line --disable-warnings -m "not slow" tests/bdd

core-bdd-slow:
	$(PYTEST) -q --color=no --tb=line --disable-warnings -m "slow" tests/bdd

cli-unit-test:
	cd cli && $(PYTEST) -q --color=no --tb=line --disable-warnings tests/unit

cli-bdd-test:
	cd cli && $(PYTEST) -q --color=no --tb=line --disable-warnings tests/bdd
