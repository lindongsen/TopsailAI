# Author: DawsonLin
# Purpose: Build, verify and test the TopsailAI Connector locally.
#
# Binaries are written to bin/ so a launcher script can find them by a stable
# path. Every test artifact is written to .tmp/, which is ignored by git, so a
# test run never leaves output in the source tree.

SHELL := /bin/bash

BIN_DIR := bin
TMP_DIR := .tmp

SERVER_PKG := ./cmd/connector-server
NODE_PKG := ./cmd/connector-node

COVERAGE_FILE := $(TMP_DIR)/coverage.out
COVERAGE_HTML := $(TMP_DIR)/coverage.html

# The unit suite is what `go test ./...` runs. Integration and BDD suites are
# behind build tags so a plain unit run stays fast and needs no built binary.
UNIT_TAGS :=
INTEGRATION_TAGS := integration
BDD_TAGS := bdd

.PHONY: help build vet test test-unit coverage coverage-html integration bdd e2e check fmt clean

help:
	@echo "Targets:"
	@echo "  build           Build connector-server and connector-node into $(BIN_DIR)/"
	@echo "  vet             Run go vet on every package"
	@echo "  test            Run the unit test suite"
	@echo "  test-unit       Run the unit test suite"
	@echo "  coverage        Run the unit suite and report per-package coverage"
	@echo "  coverage-html   Write an HTML coverage report to $(COVERAGE_HTML)"
	@echo "  integration     Build the binaries, then run the integration suite"
	@echo "  bdd             Run the Gherkin scenarios in tests/bdd/"
	@echo "  e2e             Build the binaries, then drive one read through two real processes"
	@echo "  check           vet, unit, coverage, integration, bdd and e2e in that order"
	@echo "  fmt             Format every Go source file"
	@echo "  clean           Remove build and test artifacts"

build:
	@mkdir -p $(BIN_DIR)
	go build -o $(BIN_DIR)/connector-server $(SERVER_PKG)
	go build -o $(BIN_DIR)/connector-node $(NODE_PKG)

vet:
	go vet ./...

test: test-unit

test-unit:
	@mkdir -p $(TMP_DIR)
	go test -count=1 -tags '$(UNIT_TAGS)' ./... 2>&1 | tee $(TMP_DIR)/unit-test.log

# Coverage is reported per package rather than as one number, because a single
# total hides the package that is actually untested. The profile is written to
# .tmp/ so a coverage run leaves nothing in the source tree.
coverage:
	@mkdir -p $(TMP_DIR)
	go test -count=1 -tags '$(UNIT_TAGS)' -coverprofile=$(COVERAGE_FILE) ./... 2>&1 | tee $(TMP_DIR)/coverage.log
	@go tool cover -func=$(COVERAGE_FILE) | tail -1

coverage-html: coverage
	@go tool cover -html=$(COVERAGE_FILE) -o $(COVERAGE_HTML)
	@echo "wrote $(COVERAGE_HTML)"

# The integration suite runs the real binaries, so it builds them first. It is
# tagged so `go test ./...` does not try to run it without a binary present.
integration: build
	@mkdir -p $(TMP_DIR)
	go test -count=1 -tags '$(INTEGRATION_TAGS)' ./tests/integration/... 2>&1 | tee $(TMP_DIR)/integration-test.log

# The BDD suite reads the Gherkin files in tests/bdd/ and runs the steps they
# name. It needs no built binary, because every scenario drives a library call.
bdd:
	@mkdir -p $(TMP_DIR)
	go test -count=1 -tags '$(BDD_TAGS)' ./tests/bdd/... 2>&1 | tee $(TMP_DIR)/bdd-test.log

# The end-to-end suite drives two real processes over a real socket, so it builds
# the binaries first. Depending on build is what stops a stale binary in bin/ from
# answering for source that has since changed, which would make a green run a lie.
#
# run.sh proves one read and the three refusals. reconnect.sh proves what a single
# connection cannot show: that a dead Node is refused instead of hanging, that a
# restarted Node recovers, that concurrent reads keep their own answers, and that a
# second Node with the same identity replaces the first without the first evicting
# it on the way out. long_run.sh restarts the real Node twenty times and asserts the
# Server's own log balances established against closed channels, which is the
# process-level evidence that no registration is left behind.
e2e: build
	@mkdir -p $(TMP_DIR)
	bash tests/e2e/start.sh 2>&1 | tee $(TMP_DIR)/e2e-test.log
	bash tests/e2e/run.sh 2>&1 | tee -a $(TMP_DIR)/e2e-test.log
	bash tests/e2e/reconnect.sh 2>&1 | tee -a $(TMP_DIR)/e2e-test.log
	bash tests/e2e/long_run.sh 2>&1 | tee -a $(TMP_DIR)/e2e-test.log

check: vet test-unit coverage integration bdd e2e

fmt:
	go fmt ./...

clean:
	@echo "removing $(BIN_DIR) and $(TMP_DIR)"
	rm -rf $(BIN_DIR) $(TMP_DIR)
