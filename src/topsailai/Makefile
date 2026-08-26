PYTHON ?= python
PYTEST ?= pytest

.PHONY: help core-unit-test cli-unit-test cli-bdd-test

help:
	@printf '%s\n' \
		'Available targets:' \
		'  help            Show this help message' \
		'  core-unit-test  Run core unit tests' \
		'  cli-unit-test   Run CLI unit tests' \
		'  cli-bdd-test    Run CLI BDD tests'

core-unit-test:
	$(PYTHON) tests/run_tests.py

cli-unit-test:
	cd cli && $(PYTEST) -q --color=no --tb=line --disable-warnings tests/unit

cli-bdd-test:
	cd cli && $(PYTEST) -q --color=no --tb=line --disable-warnings tests/bdd
