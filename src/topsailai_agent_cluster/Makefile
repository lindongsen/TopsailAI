# Author: DawsonLin
# Purpose: Build, verify, package and operate the Agent Cluster locally.
#
# Production binaries are written to bin/ because scripts/start-local-cluster.sh
# loads them from there. The test-hooks variant stays in .tmp/artifacts/ so that
# building instrumented binaries never overwrites the ones a running cluster uses.
#
# Debian packages are built into .tmp/deb/ and are the deployment artifact: a node
# is provisioned with `dpkg -i` instead of copying a bundle directory. The package
# carries the same payload as a bundle (controller, role binary, configuration and
# TLS material), laid out according to Debian policy.

SHELL := /bin/bash

BIN_DIR := bin
TESTHOOKS_DIR := .tmp/artifacts
DEB_DIR := .tmp/deb
LAUNCHER := scripts/start-local-cluster.sh
DEB_BUILDER := scripts/make-deb.sh

SERVER_PKG := ./src/main/agent-cluster-server
ENDPOINT_PKG := ./src/main/agent-cluster-endpoint
CLI_PKG := ./src/main/agent-cluster-cli

# Site values baked into a package. A package carries its configuration and TLS
# material, exactly like a bundle, so a real deployment overrides these:
#
#   make deb DEB_CONFIG=conf/site/node.conf DEB_CERT=... DEB_KEY=... DEB_CA=...
#
# The defaults build a package from the example configuration and the development
# certificates, which is enough to exercise the packaging path locally.
DEB_VERSION :=
DEB_REVISION := 1
DEB_ARCH :=
DEB_CONFIG :=
DEB_CERT :=
DEB_KEY :=
DEB_CA :=
DEB_ADAPTERS :=

# Passes one optional builder argument only when the variable is non-empty, so an
# unset variable never becomes an empty positional value.
deb_arg = $(if $(strip $(2)),$(1) $(2))

# Argument groups shared by the package targets. Keeping them in variables makes
# each recipe a single line, so the echoed command never shows dangling
# continuations for arguments that were not supplied.
DEB_COMMON_ARGS = $(call deb_arg,--version,$(DEB_VERSION)) \
                  $(call deb_arg,--revision,$(DEB_REVISION)) \
                  $(call deb_arg,--arch,$(DEB_ARCH))
DEB_SITE_ARGS = $(call deb_arg,--config,$(DEB_CONFIG)) \
                $(call deb_arg,--cert,$(DEB_CERT)) \
                $(call deb_arg,--key,$(DEB_KEY)) \
                $(call deb_arg,--ca,$(DEB_CA))

.DEFAULT_GOAL := help

.PHONY: help build build-testhooks vet test test-packaging bdd integration fmt \
        deb deb-node deb-server deb-endpoint deb-inspect deb-clean \
        server-start server-stop server-restart server-status \
        endpoint-start endpoint-stop endpoint-restart endpoint-status \
        cluster-start cluster-stop cluster-restart cluster-status

help:
	@echo "Usage: make <target>"
	@echo ""
	@echo "Build"
	@echo "  build             build server, endpoint and cli into $(BIN_DIR)/"
	@echo "  build-testhooks   build test-hook binaries into $(TESTHOOKS_DIR)/"
	@echo ""
	@echo "Verify"
	@echo "  vet               run go vet over all packages"
	@echo "  test              run the default suite, including the packaging tests"
	@echo "  test-packaging    run only the Debian packaging tests"
	@echo "  bdd               run the BDD feature suite"
	@echo "  integration       run the integration suite with test hooks"
	@echo "  fmt               format Go sources in place"
	@echo ""
	@echo "Package (Debian)"
	@echo "  deb               build all three packages into $(DEB_DIR)/"
	@echo "  deb-node          build the controller package only"
	@echo "  deb-server        build the server package only"
	@echo "  deb-endpoint      build the endpoint package only"
	@echo "  deb-inspect       list the packages and their control fields"
	@echo "  deb-clean         remove the package output and staging trees"
	@echo ""
	@echo "  Site values: DEB_VERSION DEB_REVISION DEB_ARCH DEB_CONFIG DEB_CERT"
	@echo "               DEB_KEY DEB_CA DEB_ADAPTERS"
	@echo ""
	@echo "Cluster lifecycle (both roles)"
	@echo "  cluster-start     start server then endpoint"
	@echo "  cluster-stop      stop endpoint then server"
	@echo "  cluster-restart   restart both roles"
	@echo "  cluster-status    report both roles"
	@echo ""
	@echo "Server lifecycle"
	@echo "  server-start      start the server only"
	@echo "  server-stop       stop the server only"
	@echo "  server-restart    restart the server only"
	@echo "  server-status     report the server only"
	@echo ""
	@echo "Endpoint lifecycle"
	@echo "  endpoint-start    start the endpoint only"
	@echo "  endpoint-stop     stop the endpoint only"
	@echo "  endpoint-restart  restart the endpoint only"
	@echo "  endpoint-status   report the endpoint only"

build:
	@mkdir -p $(BIN_DIR)
	go build -o $(BIN_DIR)/agent-cluster-server $(SERVER_PKG)
	go build -o $(BIN_DIR)/agent-cluster-endpoint $(ENDPOINT_PKG)
	go build -o $(BIN_DIR)/agent-cluster-cli $(CLI_PKG)

build-testhooks:
	@mkdir -p $(TESTHOOKS_DIR)
	go build -tags=testhooks -o $(TESTHOOKS_DIR)/agent-cluster-server $(SERVER_PKG)
	go build -tags=testhooks -o $(TESTHOOKS_DIR)/agent-cluster-endpoint $(ENDPOINT_PKG)
	go build -tags=testhooks -o $(TESTHOOKS_DIR)/agent-cluster-cli $(CLI_PKG)

vet:
	go vet ./...

test:
	go test -count=1 ./...

# The packaging tests live in an untagged package so the default suite above
# discovers them. This target runs them alone while iterating on the packager.
test-packaging:
	go test -count=1 ./tests/packaging

bdd:
	go test ./tests/bdd -count=1 -v

integration:
	go test -tags='integration testhooks' ./tests/integration -count=1

fmt:
	gofmt -w src internal

# Builds one package. The builder derives the version from git when DEB_VERSION is
# empty, so a package always identifies the commit it was built from.
deb-node:
	@mkdir -p $(DEB_DIR)
	@bash $(DEB_BUILDER) --role node --dest $(DEB_DIR) $(DEB_COMMON_ARGS)

deb-server:
	@mkdir -p $(DEB_DIR)
	@bash $(DEB_BUILDER) --role server --dest $(DEB_DIR) $(DEB_COMMON_ARGS) $(DEB_SITE_ARGS)

deb-endpoint:
	@mkdir -p $(DEB_DIR)
	@bash $(DEB_BUILDER) --role endpoint --dest $(DEB_DIR) $(DEB_COMMON_ARGS) $(DEB_SITE_ARGS) \
		$(call deb_arg,--adapters,$(DEB_ADAPTERS))

# Builds every package. Packages left by an earlier version are removed first: a
# directory holding two versions of the same package is what `dpkg -i *.deb`
# picks up, and it installs whichever file the shell happens to expand last. The
# controller package is built first because both role packages depend on it, so a
# failure there stops before the large binaries build.
#
# The version is resolved once here and pinned for all three builds. Each builder
# invocation otherwise re-derives it from git, so a commit landing mid-run yields
# a set whose role packages depend on a controller version that was never built,
# and dpkg then refuses to install the endpoint.
deb:
	@rm -f $(DEB_DIR)/agent-cluster-*.deb
	@version=$$(bash $(DEB_BUILDER) --print-version $(call deb_arg,--version,$(DEB_VERSION))) || exit 1; \
	echo "building version $$version"; \
	$(MAKE) --no-print-directory deb-node deb-server deb-endpoint DEB_VERSION="$$version"
	@echo ""
	@echo "packages in $(DEB_DIR):"
	@ls -1 $(DEB_DIR)/*.deb

# Reports what each package contains and how it is declared, which is the check
# that matters before handing a package to a node. conffiles is a separate
# control file rather than a control field, so it is read from the control
# archive; dpkg-deb -f cannot report it.
deb-inspect:
	@for package in $(DEB_DIR)/*.deb; do \
		[ -f "$${package}" ] || continue; \
		echo "=== $${package} ==="; \
		dpkg-deb -f "$${package}" Package Version Architecture Depends Conflicts; \
		echo "--- conffiles ---"; \
		dpkg-deb --ctrl-tarfile "$${package}" | tar -xO ./conffiles 2>/dev/null \
			|| echo "(none)"; \
		echo "--- contents ---"; \
		dpkg-deb -c "$${package}" | awk '{print $$1, $$6, $$7, $$8}'; \
		echo ""; \
	done

# Removes the staging tree and the built packages, which is what the help text
# promises. Keeping the packages would leave a stale version behind for the next
# `dpkg -i *.deb`.
deb-clean:
	rm -rf $(DEB_DIR)/build
	rm -f $(DEB_DIR)/agent-cluster-*.deb
	@echo "removed $(DEB_DIR)/build and $(DEB_DIR)/*.deb"

cluster-start:
	bash $(LAUNCHER) start

cluster-stop:
	bash $(LAUNCHER) stop

cluster-restart:
	bash $(LAUNCHER) restart

cluster-status:
	bash $(LAUNCHER) status

server-start:
	bash $(LAUNCHER) start-server

server-stop:
	bash $(LAUNCHER) stop-server

server-restart:
	bash $(LAUNCHER) restart-server

server-status:
	bash $(LAUNCHER) status-server

endpoint-start:
	bash $(LAUNCHER) start-endpoint

endpoint-stop:
	bash $(LAUNCHER) stop-endpoint

endpoint-restart:
	bash $(LAUNCHER) restart-endpoint

endpoint-status:
	bash $(LAUNCHER) status-endpoint
