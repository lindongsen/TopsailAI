# Author: DawsonLin
# Purpose: Build, verify and run the Mock Provider workspace.
#
# This workspace is an independent Go module, so it is built and tested here
# rather than from the cluster Makefile. The cluster targets that need this
# executable call `go build ./src` from this directory; they do not own its
# build recipe.
#
# Every generated file stays under .tmp/ so a build never writes into the source
# directory or the workspace root. The binary is written to .tmp/bin/ instead of
# the workspace root because `go build .` in the module root would drop an
# executable named after the module beside go.mod.

SHELL := /bin/bash

MODULE := agent-cluster-provider-mock
SRC := ./src
BIN_DIR := .tmp/bin
BIN := $(BIN_DIR)/$(MODULE)
TMP_ROOT := $(abspath .tmp)

# The Go toolchain writes its cache and compiler temporaries outside the
# workspace by default. Pinning both under .tmp/ keeps a build reproducible and
# keeps the residue visible, so `make clean` can remove all of it.
GO_ENV := TMPDIR=$(TMP_ROOT) GOCACHE=$(TMP_ROOT)/go-cache GOTMPDIR=$(TMP_ROOT)/go-tmp

.DEFAULT_GOAL := build

.PHONY: help build vet fmt test check clean

help:
	@echo "Usage: make <target>"
	@echo ""
	@echo "  build   build the Mock Provider into $(BIN)"
	@echo "  vet     run go vet over this module"
	@echo "  fmt     format the sources in place"
	@echo "  test    run the unit tests of this module"
	@echo "  check   vet, then test"
	@echo "  clean   remove $(BIN_DIR) and the Go cache under .tmp/"

build:
	@mkdir -p $(BIN_DIR) $(TMP_ROOT)/go-cache $(TMP_ROOT)/go-tmp
	$(GO_ENV) go build -o $(BIN) $(SRC)

vet:
	@mkdir -p $(TMP_ROOT)/go-cache $(TMP_ROOT)/go-tmp
	$(GO_ENV) go vet ./...

fmt:
	gofmt -w src

test:
	@mkdir -p $(TMP_ROOT)/go-cache $(TMP_ROOT)/go-tmp
	$(GO_ENV) go test -count=1 ./...

check: vet test

# Removes only this workspace's generated directories. Both paths are guarded
# against an empty value, because `rm -rf $(BIN_DIR)` with an empty variable
# becomes `rm -rf /`.
clean:
	@[ -n "$(BIN_DIR)" ] || { echo "BIN_DIR is empty; refusing to clean" >&2; exit 1; }
	@[ -n "$(TMP_ROOT)" ] || { echo "TMP_ROOT is empty; refusing to clean" >&2; exit 1; }
	rm -rf $(BIN_DIR) $(TMP_ROOT)/go-cache $(TMP_ROOT)/go-tmp
	@echo "removed $(BIN_DIR) and the Go cache under $(TMP_ROOT)"
