# Author: DawsonLin
# Purpose: Build, verify and test the TopsailAI Connector locally.
#
# Binaries are written to bin/ so a launcher script can find them by a stable
# path. Every test artifact is written to .tmp/, which is ignored by git, so a
# test run never leaves output in the source tree.

SHELL := /bin/bash

# `.SHELLFLAGS` is the special variable Make uses to build the shell command
# line; the leading dot is required. A plain `SHELLFLAGS` is an ordinary
# variable that Make silently ignores, which is how the first attempt at this
# fix did nothing.
#
# `-o pipefail` makes a recipe fail when any stage of a pipeline fails. Without
# it the exit status of `go test ... | tee log` is tee's status, so a failing
# suite reported success as long as tee could write the log. That defect hid a
# real BDD failure for three commits; see
# issues/issue-make-check-masks-suite-failures.md.
#
# Only `pipefail` is added. `-e` and `-u` would change nothing here: every recipe
# line already runs in its own shell, so Make stops at the first failing line
# without help, and no recipe uses a shell variable that could be unset.
.SHELLFLAGS := -o pipefail -c

# BIN_DIR and TMP_DIR are overridable from the command line, so a release build
# can write somewhere other than bin/ without editing this file:
#
#   make build BIN_DIR=/usr/local/bin
#   make build BIN_DIR=/tmp/release
#
# `?=` rather than `:=` is what makes that work: a command-line assignment wins
# over a `?=` default, and a plain `:=` would silently ignore it.
BIN_DIR ?= bin
TMP_DIR ?= .tmp

SERVER_PKG := ./cmd/connector-server
NODE_PKG := ./cmd/connector-node

# Component package groups. A component-level test target runs only the packages
# that belong to that component, so a change to the Node can be verified without
# waiting for the Server suite and vice versa. The three groups are disjoint and
# together cover every package under cmd/ and internal/, which is where all unit
# tests live. The suites under tests/ are not in any group: they are tagged and
# have their own targets (integration, bdd, e2e), so a component run never
# silently skips them by pretending to include them.
SERVER_PKGS := ./internal/server/... ./cmd/connector-server/...
NODE_PKGS := ./internal/node/... ./cmd/connector-node/...
SHARED_PKGS := ./internal/protocol/... ./internal/security/...

COVERAGE_FILE := $(TMP_DIR)/coverage.out
COVERAGE_HTML := $(TMP_DIR)/coverage.html

# Packaging inputs. `make package` builds one zip that a user unzips and starts,
# and that the operator can address with the CLI immediately.
#
# The two required inputs are the Server address and the folders to expose:
#
#   make package \
#     PACKAGE_SERVER_URL=https://connector.example.com:8443 \
#     PACKAGE_SCOPES='project=/home/me/project tool=/opt/tool'
#
# PACKAGE_SCOPES takes one or more `name=path` entries. The paths are the paths
# on the machine that will run the Node, not on this build host, because the
# bundle turns them into a policy file when it starts. A path containing spaces
# is easier to supply through PACKAGE_SCOPES_FILE, which takes a file with the
# same `name=path` lines.
#
# PACKAGE_TUNNEL_TOKEN is optional. When it is set, the bundle carries the token
# in a 0600 file so the user needs no further configuration; when it is unset,
# the bundle requires CONNECTOR_NODE_TUNNEL_TOKEN in the environment.
#
# PACKAGE_GOOS and PACKAGE_GOARCH default to this host, so a bundle for the
# operator's own machine needs no platform argument. `make package-windows`
# sets them to windows/amd64.
PACKAGE_NAME ?= connector-node-$(PACKAGE_GOOS)-$(PACKAGE_GOARCH)
PACKAGE_GOOS ?= $(shell go env GOOS)
PACKAGE_GOARCH ?= $(shell go env GOARCH)
PACKAGE_SERVER_URL ?=
PACKAGE_SCOPES ?=
PACKAGE_SCOPES_FILE ?=
PACKAGE_TUNNEL_TOKEN ?=

# The unit suite is what `go test ./...` runs. Integration and BDD suites are
# behind build tags so a plain unit run stays fast and needs no built binary.
UNIT_TAGS :=
INTEGRATION_TAGS := integration
BDD_TAGS := bdd

.PHONY: help build build-server build-node vet test test-unit test-server test-node test-shared coverage coverage-html integration bdd e2e check fmt clean build-windows test-windows-compile package package-windows

help:
	@echo "Targets:"
	@echo "  build           Build connector-server and connector-node into $(BIN_DIR)/"
	@echo "  build-server    Build only connector-server into $(BIN_DIR)/"
	@echo "  build-node      Build only connector-node into $(BIN_DIR)/"
	@echo "  vet             Run go vet on every package"
	@echo "  test            Run the unit test suite"
	@echo "  test-unit       Run the unit test suite"
	@echo "  test-server     Run the unit tests of the Server component only"
	@echo "  test-node       Run the unit tests of the Node component only"
	@echo "  test-shared     Run the unit tests of the shared packages only"
	@echo "  coverage        Run the unit suite and report per-package coverage"
	@echo "  coverage-html   Write an HTML coverage report to $(COVERAGE_HTML)"
	@echo "  integration     Build the binaries, then run the integration suite"
	@echo "  bdd             Run the Gherkin scenarios in tests/bdd/"
	@echo "  e2e             Build the binaries, then drive one read through two real processes"
	@echo "  check           vet, unit, coverage, integration, bdd and e2e in that order"
	@echo "  fmt             Format every Go source file"
	@echo "  build-windows   Cross-compile the Node for windows/amd64, arm64 and 386"
	@echo "  test-windows-compile  Compile the windows test binaries and run vet for windows"
	@echo "  package         Build a zip a user unzips and starts; needs PACKAGE_SERVER_URL and PACKAGE_SCOPES"
	@echo "  package-windows Build that zip for windows/amd64"
	@echo "  clean           Remove build and test artifacts"
	@echo ""
	@echo "Variables:"
	@echo "  BIN_DIR         Where binaries are written. Default bin. Override with"
	@echo "                  'make build BIN_DIR=/somewhere/else'"
	@echo "  TMP_DIR         Where test artifacts are written. Default .tmp"
	@echo "  PACKAGE_SERVER_URL  Server address the bundle dials. Required by package."
	@echo "                      http/https is accepted and converted to ws/wss"
	@echo "  PACKAGE_SCOPES      Folders to expose, as name=path entries. Required"
	@echo "                      by package. Example:"
	@echo "                      'PACKAGE_SCOPES=project=/home/me/project tool=/opt/tool'"
	@echo "  PACKAGE_SCOPES_FILE A file of name=path lines, for paths with spaces"
	@echo "  PACKAGE_TUNNEL_TOKEN Optional tunnel_token to embed in the bundle"
	@echo "  PACKAGE_NAME        Bundle name. Default connector-node-<goos>-<goarch>"
	@echo "  PACKAGE_GOOS        Target OS. Default this host"
	@echo "  PACKAGE_GOARCH      Target architecture. Default this host"

build: build-server build-node

build-server:
	@mkdir -p $(BIN_DIR)
	go build -o $(BIN_DIR)/connector-server $(SERVER_PKG)

build-node:
	@mkdir -p $(BIN_DIR)
	go build -o $(BIN_DIR)/connector-node $(NODE_PKG)

vet:
	go vet ./...

test: test-unit

test-unit:
	@mkdir -p $(TMP_DIR)
	go test -count=1 -tags '$(UNIT_TAGS)' ./... 2>&1 | tee $(TMP_DIR)/unit-test.log

# Component-level unit runs. Each one covers a disjoint package group, so a
# failure names the component that broke instead of leaving the reader to work it
# out from a package path. `make test` remains the full run and is what `check`
# uses, because a component run alone would not notice a change that broke the
# other side.
test-server:
	@mkdir -p $(TMP_DIR)
	go test -count=1 -tags '$(UNIT_TAGS)' $(SERVER_PKGS) 2>&1 | tee $(TMP_DIR)/unit-test-server.log

test-node:
	@mkdir -p $(TMP_DIR)
	go test -count=1 -tags '$(UNIT_TAGS)' $(NODE_PKGS) 2>&1 | tee $(TMP_DIR)/unit-test-node.log

test-shared:
	@mkdir -p $(TMP_DIR)
	go test -count=1 -tags '$(UNIT_TAGS)' $(SHARED_PKGS) 2>&1 | tee $(TMP_DIR)/unit-test-shared.log

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

# Windows is a supported platform for the Node, so the Node must be compiled for
# it on every check. The Server is deployed on Linux and is not built here: a
# Windows Server binary would be a build nobody runs, and a target that produces
# one invites the belief that the Server is supported there.
#
# The cross build is not a substitute for running the suite on Windows, but it is
# the only check that catches a POSIX-only import or a syscall that does not exist
# on Windows. Without it nothing in this repository ever compiles for Windows.
build-windows:
	@mkdir -p $(TMP_DIR)/xbuild
	GOOS=windows GOARCH=amd64 go build -o $(TMP_DIR)/xbuild/connector-node-amd64.exe $(NODE_PKG)
	GOOS=windows GOARCH=arm64 go build -o $(TMP_DIR)/xbuild/connector-node-arm64.exe $(NODE_PKG)
	GOOS=windows GOARCH=386 go build -o $(TMP_DIR)/xbuild/connector-node-386.exe $(NODE_PKG)
	@echo "built the Node for windows/amd64, windows/arm64 and windows/386"

# Compiling the test binaries proves the test code is portable too. A test that
# imports syscall or calls Mkfifo compiles on Linux and breaks the Windows build,
# so the test sources are part of the platform contract rather than a local
# convenience.
test-windows-compile:
	@mkdir -p $(TMP_DIR)/xbuild
	GOOS=windows GOARCH=amd64 go vet ./...
	GOOS=windows GOARCH=amd64 go test -c -o $(TMP_DIR)/xbuild/node.test.exe ./internal/node/
	GOOS=windows GOARCH=amd64 go test -c -o $(TMP_DIR)/xbuild/policy.test.exe ./internal/node/policy/
	GOOS=windows GOARCH=amd64 go test -c -o $(TMP_DIR)/xbuild/protocol.test.exe ./internal/protocol/
	GOOS=windows GOARCH=amd64 go test -c -o $(TMP_DIR)/xbuild/security.test.exe ./internal/security/
	GOOS=windows GOARCH=amd64 go test -c -o $(TMP_DIR)/xbuild/connector-node.test.exe ./cmd/connector-node/
	@echo "compiled the windows test binaries"

# package builds one zip that a user unzips and starts, and that the operator can
# address with the CLI immediately.
#
# It depends on build-node because the identity pair is generated with the host
# build of the Node. Generating the pair with a second implementation here would
# be a second definition of the pair format, and the two would eventually
# disagree about what a valid pair is.
#
# The scope paths are not baked into a policy file. A policy requires absolute
# paths, and the build host's paths are not the user's paths, so the bundle
# carries an editable scopes.txt and its start script writes policy.yaml on the
# machine that will serve the files. That is what makes the same zip usable on a
# machine whose folders this host has never seen.
#
# The bundle is a credential bundle: it carries the Node's identity pair and,
# when PACKAGE_TUNNEL_TOKEN is set, the tunnel token. The script prints the pair
# so the operator can copy it into the CLI, and says so rather than leaving it to
# be discovered.
package: build-node
	@PACKAGE_NAME='$(PACKAGE_NAME)' \
	PACKAGE_GOOS='$(PACKAGE_GOOS)' \
	PACKAGE_GOARCH='$(PACKAGE_GOARCH)' \
	PACKAGE_SERVER_URL='$(PACKAGE_SERVER_URL)' \
	PACKAGE_SCOPES='$(PACKAGE_SCOPES)' \
	PACKAGE_SCOPES_FILE='$(PACKAGE_SCOPES_FILE)' \
	PACKAGE_TUNNEL_TOKEN='$(PACKAGE_TUNNEL_TOKEN)' \
	BIN_DIR='$(BIN_DIR)' \
	TMP_DIR='$(TMP_DIR)' \
	bash packaging/build-package.sh

# package-windows is the same bundle for windows/amd64, which is the platform the
# Node is most often handed to a user on. It is a separate target rather than a
# variable the caller must remember, because forgetting it produces a Linux
# binary in a zip that a Windows user cannot run, and the failure appears on
# their machine rather than here.
package-windows:
	@$(MAKE) --no-print-directory package PACKAGE_GOOS=windows PACKAGE_GOARCH=amd64

check: vet test-unit coverage integration bdd e2e build-windows test-windows-compile

fmt:
	go fmt ./...

clean:
	@echo "removing $(BIN_DIR) and $(TMP_DIR)"
	rm -rf $(BIN_DIR) $(TMP_DIR)
