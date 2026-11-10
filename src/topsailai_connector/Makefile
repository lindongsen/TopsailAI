# Author: DawsonLin
# Purpose: Build, verify and test the TopsailAI Connector locally.
#
# Binaries are written to bin/ so a launcher script can find them by a stable
# path. Test artifacts are written to .tmp/, which is ignored by git, so a test
# run never leaves output in the source tree.

SHELL := /bin/bash

BIN_DIR := bin
TMP_DIR := .tmp

SERVER_PKG := ./cmd/connector-server
NODE_PKG := ./cmd/connector-node

.PHONY: help build vet test test-unit fmt clean

help:
	@echo "Targets:"
	@echo "  build      Build connector-server and connector-node into $(BIN_DIR)/"
	@echo "  vet        Run go vet on every package"
	@echo "  test       Run the unit test suite"
	@echo "  test-unit  Run the unit test suite"
	@echo "  fmt        Format every Go source file"
	@echo "  clean      Remove build and test artifacts"

build:
	@mkdir -p $(BIN_DIR)
	go build -o $(BIN_DIR)/connector-server $(SERVER_PKG)
	go build -o $(BIN_DIR)/connector-node $(NODE_PKG)

vet:
	go vet ./...

test: test-unit

test-unit:
	@mkdir -p $(TMP_DIR)
	go test -count=1 ./... 2>&1 | tee $(TMP_DIR)/unit-test.log

fmt:
	go fmt ./...

clean:
	@echo "removing $(BIN_DIR) and $(TMP_DIR)"
	rm -rf $(BIN_DIR) $(TMP_DIR)
