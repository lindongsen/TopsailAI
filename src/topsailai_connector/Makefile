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

# Packaging inputs. `make package` builds one executable with the configuration
# compiled in, and that the operator can address with the CLI immediately. Set
# PACKAGE_EMBED_CONFIG=0, or run `make package-zip`, for a zip that a user unzips
# and starts instead.
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
# PACKAGE_ALLOW_FILESYSTEM_ROOT is off by default and is the only way a bundle
# can expose a whole volume. When it is set to 1, the bundle's start script
# accepts a scope whose path is a drive root (`C:\`) or `/`, and the generated
# policy carries `allow_filesystem_root: true`. The Node still refuses such a
# scope unless that key is present, so the decision is written down at packaging
# time by the operator who understands the blast radius, rather than by whoever
# receives the bundle and edits scopes.txt. The bundle's own config directory
# stays unreadable through such a scope: the Node denies it by resolved path and
# omits it from a listing.
#
# PACKAGE_EMBED_CONFIG selects the packaging mode, and it defaults to 1: `make
# package` produces one executable instead of a zip. The Server URL, the policy
# and, when PACKAGE_TUNNEL_TOKEN is set, the tunnel token are compiled into the
# binary, so the recipient runs it and the Node connects with no configuration
# file and no environment variable.
#
# Set PACKAGE_EMBED_CONFIG=0 to get the zip instead. The zip is the mode to pick
# when the recipient must edit the scopes themselves, when the policy must be
# reloadable on SIGHUP, or when one artifact must not carry the Server-wide
# tunnel token.
#
# The identity is deliberately not embedded. It is generated on first start,
# polled every second and rewritten by `regenerate`, and two copies of one binary
# would share a node-id, which makes the Server's registry evict the first.
#
# A binary built this way carries a credential, so the Node adds its own
# executable to the deny list: a scope that contains the binary cannot serve it.
# The values are stored as plain text in the binary, so `strings` recovers them.
# A leaked zip exposes one Node's identity; a leaked embedded binary exposes the
# tunnel token, which gates every Node on that Server.
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
PACKAGE_ALLOW_FILESYSTEM_ROOT ?=
PACKAGE_EMBED_CONFIG ?= 1

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
	@echo "  e2e             Build the binaries, then drive real processes and a real bundle"
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
	@echo "  PACKAGE_ALLOW_FILESYSTEM_ROOT  Set to 1 to let a bundle expose a whole"
	@echo "                      volume (C:\\ or /). Off by default. The Node still"
	@echo "                      denies the bundle's own config directory"
	@echo "  PACKAGE_TUNNEL_TOKEN Optional tunnel_token to embed in the bundle"
	@echo "  PACKAGE_EMBED_CONFIG  Packaging mode. Default 1: one executable with"
	@echo "                      the configuration compiled in, needing no file and"
	@echo "                      no environment variable. Set to 0 for a zip, which"
	@echo "                      the recipient can edit and reload. The executable"
	@echo "                      carries the tunnel token, so treat it as a"
	@echo "                      credential: a leak exposes every Node on the Server"
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
#
# verify_package.sh is the only check that exercises the delivery path: it builds a
# real zip, unzips it, and starts the bundle with the bundle's own start script
# rather than with a command written for the test. A bundle that is well formed but
# cannot start is exactly the failure the other scripts cannot see, because they
# never run the artifact that is handed to another person. It also asserts the
# filesystem-root opt-in: off by default, on only when the packaging operator asked
# for it, and never a way to allow the home directory.
e2e: build
	@mkdir -p $(TMP_DIR)
	bash tests/e2e/start.sh 2>&1 | tee $(TMP_DIR)/e2e-test.log
	bash tests/e2e/run.sh 2>&1 | tee -a $(TMP_DIR)/e2e-test.log
	bash tests/e2e/reconnect.sh 2>&1 | tee -a $(TMP_DIR)/e2e-test.log
	bash tests/e2e/long_run.sh 2>&1 | tee -a $(TMP_DIR)/e2e-test.log
	bash tests/e2e/verify_package.sh 2>&1 | tee -a $(TMP_DIR)/e2e-test.log

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

# package builds one executable with the configuration compiled in, and that the
# operator can address with the CLI immediately. Set PACKAGE_EMBED_CONFIG=0, or
# run `make package-zip`, for a zip that a user unzips and starts instead.
#
# It depends on build-node because the zip mode generates the identity pair with
# the host build of the Node. Generating the pair with a second implementation
# here would be a second definition of the pair format, and the two would
# eventually disagree about what a valid pair is. The default mode does not read
# the host binary, because the identity is created on the target machine, so the
# dependency is only load-bearing for the zip.
#
# The scope paths are not baked into a policy file. A policy requires absolute
# paths, and the build host's paths are not the user's paths, so the bundle
# carries an editable scopes.txt and its start script writes policy.yaml on the
# machine that will serve the files. That is what makes the same zip usable on a
# machine whose folders this host has never seen.
#
# The artifact is a credential artifact either way. The default mode compiles the
# configuration into one executable, so the file carries the tunnel token and a
# leak exposes every Node on that Server. The zip mode carries the Node's identity
# pair, and the tunnel token when PACKAGE_TUNNEL_TOKEN is set, so a leak exposes
# one Node. The script prints what the artifact carries and says so rather than
# leaving it to be discovered.
package: build-node
	@PACKAGE_NAME='$(PACKAGE_NAME)' \
	PACKAGE_GOOS='$(PACKAGE_GOOS)' \
	PACKAGE_GOARCH='$(PACKAGE_GOARCH)' \
	PACKAGE_SERVER_URL='$(PACKAGE_SERVER_URL)' \
	PACKAGE_SCOPES='$(PACKAGE_SCOPES)' \
	PACKAGE_SCOPES_FILE='$(PACKAGE_SCOPES_FILE)' \
	PACKAGE_TUNNEL_TOKEN='$(PACKAGE_TUNNEL_TOKEN)' \
	PACKAGE_ALLOW_FILESYSTEM_ROOT='$(PACKAGE_ALLOW_FILESYSTEM_ROOT)' \
	PACKAGE_EMBED_CONFIG='$(PACKAGE_EMBED_CONFIG)' \
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

# package-embedded is kept as an explicit spelling of the default mode: one
# executable with the Server URL, the policy and, when PACKAGE_TUNNEL_TOKEN is
# set, the tunnel token compiled in. It now only restates the default, so a
# script that already calls it keeps working after the default changed.
#
# The identity is not embedded, so the recipient runs the binary once with `id`
# to create it. That is stated in the summary the script prints.
package-embedded:
	@$(MAKE) --no-print-directory package PACKAGE_EMBED_CONFIG=1

# package-embedded-windows is package-embedded for windows/amd64.
package-embedded-windows:
	@$(MAKE) --no-print-directory package PACKAGE_EMBED_CONFIG=1 PACKAGE_GOOS=windows PACKAGE_GOARCH=amd64

# package-zip is the opt-out: a zip with a start script, an editable scopes.txt
# and a policy the Node reloads on SIGHUP. It exists as a named target so a
# caller who wants the zip does not have to remember the variable.
package-zip:
	@$(MAKE) --no-print-directory package PACKAGE_EMBED_CONFIG=0

# package-zip-windows is package-zip for windows/amd64.
package-zip-windows:
	@$(MAKE) --no-print-directory package PACKAGE_EMBED_CONFIG=0 PACKAGE_GOOS=windows PACKAGE_GOARCH=amd64

check: vet test-unit coverage integration bdd e2e build-windows test-windows-compile

fmt:
	go fmt ./...

clean:
	@echo "removing $(BIN_DIR) and $(TMP_DIR)"
	rm -rf $(BIN_DIR) $(TMP_DIR)
