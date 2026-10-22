# Session Agent Driver test commands.

PYTHON ?= python
PYTEST ?= pytest
MAKEFILE_DIR := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
SOURCE_ROOT := $(MAKEFILE_DIR)/../../..
TMP_DIR := $(MAKEFILE_DIR)/.tmp/make
PYTEST_ARGS := --color=no --tb=line --disable-warnings

.PHONY: help test test-unit test-bdd syntax

help:
	@printf '%s\n' \
		'Available targets:' \
		'  help       Show this help message' \
		'  test       Run unit and BDD tests' \
		'  test-unit  Run non-BDD unit tests' \
		'  test-bdd   Run BDD tests' \
		'  syntax     Check Python syntax'

test: test-unit test-bdd

test-unit:
	cd $(MAKEFILE_DIR) && PYTHONPATH=$(SOURCE_ROOT) $(PYTEST) $(PYTEST_ARGS) tests --ignore=tests/bdd

test-bdd:
	cd $(MAKEFILE_DIR) && PYTHONPATH=$(SOURCE_ROOT) $(PYTEST) $(PYTEST_ARGS) tests/bdd

syntax:
	@mkdir -p $(TMP_DIR)
	cd $(MAKEFILE_DIR) && PYTHONPYCACHEPREFIX=$(TMP_DIR)/pycache PYTHONPATH=$(SOURCE_ROOT) $(PYTHON) -m compileall -q -f .
