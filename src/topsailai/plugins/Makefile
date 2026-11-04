# Independent plugin tests; author: DawsonLin.
UV ?= uv
PYTHON ?= $(UV) run python
WORKSPACE := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
CORE_ROOT := $(abspath $(WORKSPACE)/..)
TEMP_ROOT := $(CORE_ROOT)/.tmp/plugins-workspace
TEST_ENV := PYTHONPATH=$(WORKSPACE)/tools:$(WORKSPACE)/tests:$(CORE_ROOT):$(abspath $(CORE_ROOT)/..) PYTHONDONTWRITEBYTECODE=1 TMPDIR=$(TEMP_ROOT) TOPSAILAI_HOME=$(TEMP_ROOT)/home TOPSAILAI_EVENTS_ENABLED=0
PYTEST_FLAGS = -q --color=no --tb=short --disable-warnings -p no:cacheprovider --basetemp=$(TEMP_ROOT)/runs/$@

.PHONY: test test-unit test-bdd
test: test-unit test-bdd

test-unit:
	@mkdir -p $(TEMP_ROOT)/runs
	cd $(WORKSPACE) && $(TEST_ENV) $(PYTHON) -B -m pytest $(PYTEST_FLAGS) $(WORKSPACE)/tests --ignore=$(WORKSPACE)/tests/test_agent_plugin_bdd.py

test-bdd:
	@mkdir -p $(TEMP_ROOT)/runs
	cd $(WORKSPACE) && $(TEST_ENV) $(PYTHON) -B -m pytest $(PYTEST_FLAGS) $(WORKSPACE)/tests/test_agent_plugin_bdd.py
