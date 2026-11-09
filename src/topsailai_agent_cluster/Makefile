# Author: DawsonLin
# Purpose: Build, verify, package and operate the Agent Cluster locally.
#
# Production binaries are written to bin/ because scripts/start-local-cluster.sh
# loads them from there. The test-hooks variant stays in .tmp/artifacts/ so that
# building instrumented binaries never overwrites the ones a running cluster uses.
#
# Debian packages are built into DEB_DIR and are the deployment artifact: a node
# is provisioned with `dpkg -i` instead of copying a bundle directory. The package
# carries the same payload as a bundle (controller, role binary, configuration and
# TLS material), laid out according to Debian policy.
#
# DEB_DIR and DEB_BUILD_DIR are overridable so a release build can write the
# artifacts outside the source tree, for example into a mounted volume or a CI
# artifact directory. Both default to .tmp/, which is ignored by git. Override
# them on the command line or through the environment:
#
#   make deb DEB_DIR=/srv/artifacts/deb
#   DEB_DIR=/srv/artifacts/deb make deb
#
# The staging tree is kept separate from the output directory on purpose: a
# staging tree inside the output directory would be swept by `deb-clean` and
# would also be picked up by a `dpkg -i *.deb` glob if it ever held a package.

SHELL := /bin/bash

BIN_DIR := bin
TESTHOOKS_DIR := .tmp/artifacts
DEB_DIR ?= .tmp/deb
DEB_BUILD_DIR ?= .tmp/deb/build
LAUNCHER := scripts/start-local-cluster.sh
DEB_BUILDER := scripts/make-deb.sh
# Container image for the server. The tag defaults to the commit the image was
# built from, so an image always identifies its source; `latest` is added as a
# convenience alias for the same build.
#
# The build uses the host network because this host's containers have no outbound
# route: the default bridge resolves nothing and even a direct IP connection
# times out, so `go mod download` cannot reach a module proxy. The host network
# borrows the host's resolver and route, which is the only path that works here.
IMAGE_REPO := agent-cluster-server
IMAGE_TAG := $(shell git rev-parse --short HEAD)
IMAGE_DOCKERFILE := docker/Dockerfile
IMAGE_NETWORK := host
IMAGE_NAME := $(IMAGE_REPO):$(IMAGE_TAG)

# Runtime wiring for `make image-run`. The container publishes both ports on the
# host so endpoints reach it through a bridge gateway address instead of the
# container IP, which changes on every recreate. TLS material and the SQLite
# database are mounted from /opt/agent-cluster, the same real directories the
# packaged node uses, and each mount point is the same path inside the container.
# A host path that differs from the container path makes an operator translate
# between two names for one file, so the image and a package would disagree about
# where state lives even while pointing at the same bytes.
IMAGE_CONTAINER := agent-cluster-server
IMAGE_NET := bind9-net
IMAGE_API_PORT := 53680
IMAGE_CHANNEL_PORT := 53943
IMAGE_CERTS_DIR := /opt/agent-cluster/certs
# Absolute path on purpose: the container state directory must be a real
# directory on a filesystem with free space. /opt/agent-cluster/data is now a real
# directory, so it is the single state location for both the packaged node and the
# container.
IMAGE_DATA_DIR := /opt/agent-cluster/data
IMAGE_TOKEN := $(shell sed -n 's/^AUTH_TOKEN=//p' /opt/agent-cluster/conf/node.conf 2>/dev/null | head -1)

SERVER_PKG := ./src/main/agent-cluster-server
ENDPOINT_PKG := ./src/main/agent-cluster-endpoint
CLI_PKG := ./src/main/agent-cluster-cli

# Test package groups, one per component. They are explicit lists rather than
# directory patterns because package ownership is not the same as directory
# nesting: internal/channel is shared by Server and Endpoint, so it belongs to
# common and must not be verified twice, while internal/adapter is Endpoint-only
# even though it sits beside shared packages. A new package therefore has to be
# assigned to a group deliberately instead of being picked up by accident.
#
# common: packages both roles depend on, plus the module root.
COMMON_TEST_PKGS := ./internal ./internal/protocol ./internal/config \
                    ./internal/logging ./internal/security ./internal/channel
# server: the Server service, its storage and its command entry point.
SERVER_TEST_PKGS := ./internal/server ./internal/storage/server \
                    ./src/main/agent-cluster-server
# endpoint: the Endpoint service, its adapters, its storage and its entry point.
ENDPOINT_TEST_PKGS := ./internal/adapter ./internal/adapter/topsailai \
                      ./internal/endpoint ./internal/storage/endpoint \
                      ./src/main/agent-cluster-endpoint
# cli: the operator client, the TUI and the CLI entry point.
CLI_TEST_PKGS := ./internal/client ./internal/tui ./src/main/agent-cluster-cli

# Site values baked into a config package. The binary packages carry no site
# data, so a real deployment overrides these only when building the config
# package for one site:
#
#   make deb-config-endpoint DEB_SITE=ai-dev DEB_CONFIG=conf/site/node.conf \
#        DEB_CERT=... DEB_KEY=... DEB_CA=...
#
# The defaults build a config package from the example configuration and the
# development certificates, which is enough to exercise the packaging path
# locally. DEB_SITE has no default because a config package name must name its
# site; the builder refuses a config build without it.
DEB_VERSION :=
DEB_REVISION := 1
DEB_ARCH :=
DEB_CONFIG :=
DEB_CERT :=
DEB_KEY :=
DEB_CA :=
DEB_ADAPTERS :=
# Site identifier that suffixes a config package name. Two sites build config
# packages with identical names and versions but different contents, so without
# this suffix dpkg cannot tell them apart and accepts the wrong one silently.
DEB_SITE :=

# Passes one optional builder argument only when the variable is non-empty, so an
# unset variable never becomes an empty positional value.
deb_arg = $(if $(strip $(2)),$(1) $(2))

# Argument groups shared by the package targets. Keeping them in variables makes
# each recipe a single line, so the echoed command never shows dangling
# continuations for arguments that were not supplied.
DEB_COMMON_ARGS = $(call deb_arg,--version,$(DEB_VERSION)) \
                  $(call deb_arg,--revision,$(DEB_REVISION)) \
                  $(call deb_arg,--arch,$(DEB_ARCH))
DEB_SITE_ARGS = $(call deb_arg,--site,$(DEB_SITE)) \
                $(call deb_arg,--config,$(DEB_CONFIG)) \
                $(call deb_arg,--cert,$(DEB_CERT)) \
                $(call deb_arg,--key,$(DEB_KEY)) \
                $(call deb_arg,--ca,$(DEB_CA))

.DEFAULT_GOAL := help

.PHONY: help build build-testhooks vet fmt \
        test test-all test-unit test-unit-common test-unit-server \
        test-unit-endpoint test-unit-cli test-bdd test-integration \
        test-packaging test-harness bdd integration \
        deb deb-node deb-server deb-endpoint deb-config-server deb-config-endpoint \
        deb-inspect deb-clean \
        image image-build image-run image-stop image-inspect image-clean \
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
	@echo "  fmt               format Go sources in place"
	@echo ""
	@echo "  Test by kind"
	@echo "  test              run every untagged test (unit, harness, packaging, bdd)"
	@echo "  test-all          run every test kind, including the tagged integration suite"
	@echo "  test-unit         run the unit tests of every component"
	@echo "  test-bdd          run the BDD feature suite"
	@echo "  test-integration  run the integration suite with test hooks"
	@echo "  test-packaging    run the Debian packaging tests"
	@echo "  test-harness      run the test-harness self-tests"
	@echo ""
	@echo "  Test by component (unit tests)"
	@echo "  test-unit-common  run the shared packages: protocol, config, logging,"
	@echo "                    security, channel and the module root"
	@echo "  test-unit-server  run the Server service, storage and entry point"
	@echo "  test-unit-endpoint run the Endpoint service, adapters, storage and entry point"
	@echo "  test-unit-cli     run the operator client, TUI and CLI entry point"
	@echo ""
	@echo "  bdd, integration  aliases kept for the older target names"
	@echo ""
	@echo "Package (Debian)"
	@echo "  deb               build every package into $(DEB_DIR)/"
	@echo "  deb-node          build the controller package only"
	@echo "  deb-server        build the server binary package only"
	@echo "  deb-endpoint      build the endpoint binary package only"
	@echo "  deb-config-server build the server site configuration package only"
	@echo "  deb-config-endpoint build the endpoint site configuration package only"
	@echo "  deb-inspect       list the packages and their control fields"
	@echo "  deb-clean         remove the package output and staging trees"
	@echo ""
	@echo "  Site values: DEB_VERSION DEB_REVISION DEB_ARCH DEB_CONFIG DEB_CERT"
	@echo "               DEB_KEY DEB_CA DEB_ADAPTERS"
	@echo "  Config package: DEB_SITE is required and suffixes the package name,"
	@echo "                  so two sites produce distinguishable artifacts"
	@echo "  Output paths: DEB_DIR (default $(DEB_DIR))"
	@echo "                DEB_BUILD_DIR (default $(DEB_BUILD_DIR))"
	@echo "                override either to write outside the source tree,"
	@echo "                e.g. make deb DEB_DIR=/srv/artifacts/deb"
	@echo ""
	@echo "Container image (server)"
	@echo "  image             build the server image as $(IMAGE_NAME)"
	@echo "  image-build       build the image only"
	@echo "  image-run         run the image on $(IMAGE_NET) with published ports"
	@echo "  image-stop        stop and remove the running container"
	@echo "  image-inspect     report the image id, size and health"
	@echo "  image-clean       remove the image built from this commit"
	@echo ""
	@echo "  Overrides: IMAGE_TAG IMAGE_NET IMAGE_API_PORT IMAGE_CHANNEL_PORT"
	@echo "             IMAGE_CERTS_DIR IMAGE_DATA_DIR IMAGE_TOKEN"
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

# Unit tests are grouped by component so a failure names the component that owns
# it, and so one component can be verified without paying for the others. The
# groups are the explicit package lists above, not a directory pattern:
# internal/channel is shared by Server and Endpoint, so it is verified once with
# common instead of twice, and a new package has to be assigned deliberately.
test-unit: test-unit-common test-unit-server test-unit-endpoint test-unit-cli

test-unit-common:
	go test -count=1 $(COMMON_TEST_PKGS)

test-unit-server:
	go test -count=1 $(SERVER_TEST_PKGS)

test-unit-endpoint:
	go test -count=1 $(ENDPOINT_TEST_PKGS)

test-unit-cli:
	go test -count=1 $(CLI_TEST_PKGS)

# The BDD suite is cross-component on purpose: a scenario drives the real Server,
# Endpoint and CLI together, so splitting it by component would either duplicate
# scenarios or assert a component in isolation, which the unit groups already do.
# The feature files are registered in tests/bdd/suite_test.go.
test-bdd:
	go test ./tests/bdd -count=1 -v

# The integration suite is cross-component for the same reason, and it needs the
# testhooks build tag because it exercises fault injection inside the binaries.
test-integration:
	go test -tags='integration testhooks' ./tests/integration -count=1

# The packaging tests live in an untagged package so the default suite below
# discovers them. This target runs them alone while iterating on the packager.
test-packaging:
	go test -count=1 ./tests/packaging

# tests/harness is test support rather than a component: its tests start real
# Server, Endpoint and fixture processes, so it is verified on its own instead of
# being folded into a component group.
test-harness:
	go test -count=1 ./tests/harness

# The default suite is every untagged test, which is what `go test ./...` already
# covers: the unit groups, the harness package, the packaging tests and the BDD
# suite. The tagged integration suite is not included, so `test-all` is the target
# that verifies everything.
test:
	go test -count=1 ./...

# Full verification: every test kind, including the tagged integration suite.
test-all: test-unit test-bdd test-integration test-packaging test-harness

# Kept as aliases because earlier plans and habits refer to these names.
bdd: test-bdd

integration: test-integration

fmt:
	gofmt -w src internal

# Builds one package. The builder derives the version from git when DEB_VERSION is
# empty, so a package always identifies the commit it was built from.
deb-node:
	@mkdir -p $(DEB_DIR)
	@bash $(DEB_BUILDER) --role node --dest $(DEB_DIR) --build-dir $(DEB_BUILD_DIR) $(DEB_COMMON_ARGS)

deb-server:
	@mkdir -p $(DEB_DIR)
	@bash $(DEB_BUILDER) --role server --dest $(DEB_DIR) --build-dir $(DEB_BUILD_DIR) $(DEB_COMMON_ARGS)

deb-endpoint:
	@mkdir -p $(DEB_DIR)
	@bash $(DEB_BUILDER) --role endpoint --dest $(DEB_DIR) --build-dir $(DEB_BUILD_DIR) $(DEB_COMMON_ARGS)

# Builds the site configuration package for one role. It carries node.conf and the
# TLS identity, so it is built per site and is not interchangeable between
# machines. The binary packages stay generic, which is what keeps a private key out
# of an artifact that is copied to every node.
deb-config-server:
	@mkdir -p $(DEB_DIR)
	@bash $(DEB_BUILDER) --role config --config-role server --dest $(DEB_DIR) --build-dir $(DEB_BUILD_DIR) $(DEB_COMMON_ARGS) $(DEB_SITE_ARGS)

deb-config-endpoint:
	@mkdir -p $(DEB_DIR)
	@bash $(DEB_BUILDER) --role config --config-role endpoint --dest $(DEB_DIR) --build-dir $(DEB_BUILD_DIR) $(DEB_COMMON_ARGS) $(DEB_SITE_ARGS) \
		$(call deb_arg,--adapters,$(DEB_ADAPTERS))

# Builds every package. Packages left by an earlier version are removed first: a
# directory holding two versions of the same package is what `dpkg -i *.deb`
# picks up, and it installs whichever file the shell happens to expand last. The
# controller package is built first because every other package depends on it, so
# a failure there stops before the large binaries build.
#
# The version is resolved once here and pinned for every build. Each builder
# invocation otherwise re-derives it from git, so a commit landing mid-run yields
# a set whose packages depend on a controller version that was never built, and
# dpkg then refuses to install them.
#
# The config packages are built last because they depend on nothing else and are
# the only artifacts that carry site data. A site that only needs to change its
# certificate rebuilds one config package instead of the whole set.
#
# DEB_SITE is required because a config package name carries its site. Building
# the whole set without one would produce a config package that cannot be told
# apart from another site's, which is the defect the suffix exists to prevent.
deb:
	@[ -n "$(DEB_DIR)" ] || { echo "DEB_DIR is empty; refusing to build" >&2; exit 1; }
	@[ -n "$(DEB_BUILD_DIR)" ] || { echo "DEB_BUILD_DIR is empty; refusing to build" >&2; exit 1; }
	@[ -n "$(DEB_SITE)" ] || { echo "DEB_SITE is empty; a config package name carries its site, so pass DEB_SITE=<site>" >&2; exit 1; }
	@rm -f $(DEB_DIR)/agent-cluster-*.deb
	@version=$$(bash $(DEB_BUILDER) --print-version $(call deb_arg,--version,$(DEB_VERSION))) || exit 1; \
	echo "building version $$version"; \
	$(MAKE) --no-print-directory deb-node deb-server deb-endpoint \
		deb-config-server deb-config-endpoint DEB_VERSION="$$version"
	@echo ""
	@echo "packages in $(DEB_DIR):"
	@ls -1 $(DEB_DIR)/*.deb

# Reports what each package contains and how it is declared, which is the check
# that matters before handing a package to a node. conffiles is a separate
# control file rather than a control field, so it is read from the control
# archive; dpkg-deb -f cannot report it. Provides is printed because a config
# package name carries its site, so the unsuffixed virtual name it provides is the
# only thing that shows the generic binary package's dependency is satisfiable.
deb-inspect:
	@for package in $(DEB_DIR)/*.deb; do \
		[ -f "$${package}" ] || continue; \
		echo "=== $${package} ==="; \
		dpkg-deb -f "$${package}" Package Version Architecture Depends Provides Conflicts; \
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
#
# The staging tree is removed from DEB_BUILD_DIR, not from inside DEB_DIR, because
# the two are independent overrides. Both are guarded against an empty value: an
# empty override would turn the removal into a path relative to the filesystem
# root, which is never what the caller meant.
deb-clean:
	@[ -n "$(DEB_DIR)" ] || { echo "DEB_DIR is empty; refusing to clean" >&2; exit 1; }
	@[ -n "$(DEB_BUILD_DIR)" ] || { echo "DEB_BUILD_DIR is empty; refusing to clean" >&2; exit 1; }
	rm -rf $(DEB_BUILD_DIR)
	rm -f $(DEB_DIR)/agent-cluster-*.deb
	@echo "removed $(DEB_BUILD_DIR) and $(DEB_DIR)/*.deb"

# Builds the server image. The context is the project directory and .dockerignore
# keeps the 183 MB .tmp tree, the databases and the TLS private keys out of it.
# Both the commit tag and `latest` point at the same build so a run command can
# use either name without silently picking a different image.
image: image-build

image-build:
	docker build --network $(IMAGE_NETWORK) -f $(IMAGE_DOCKERFILE) \
		-t $(IMAGE_NAME) -t $(IMAGE_REPO):latest .

# Runs the image with the ports published on the host. Publishing is what makes
# the container address-independent: endpoints dial a bridge gateway address, so
# a new container IP after a recreate changes nothing on their side.
#
# The state directory is shared with the host endpoint, so ownership is granted
# per entry instead of recursively: the directory and the server database belong
# to the image's unprivileged uid, while the endpoint database keeps its own
# owner. A recursive chown would hand the endpoint database to the container and
# weaken the isolation that keeps it unreadable there. SQLite reports a
# permission failure as "out of memory (14)", which hides the real cause.
image-run:
	@test -n "$(IMAGE_TOKEN)" || { echo "ERROR: no AUTH_TOKEN found; set IMAGE_TOKEN"; exit 1; }
	@mkdir -p $(IMAGE_CERTS_DIR) $(IMAGE_DATA_DIR)
	@chown 10001:10001 $(IMAGE_DATA_DIR)
	@chown 10001:10001 $(IMAGE_DATA_DIR)/server.sqlite* 2>/dev/null || true
	docker run -d --name $(IMAGE_CONTAINER) --network $(IMAGE_NET) \
		-p $(IMAGE_API_PORT):53680 -p $(IMAGE_CHANNEL_PORT):53943 \
		-e AGENT_CLUSTER_AUTH_TOKEN=$(IMAGE_TOKEN) \
		-v $(IMAGE_CERTS_DIR):/opt/agent-cluster/certs:ro \
		-v $(IMAGE_DATA_DIR):/opt/agent-cluster/data \
		--restart unless-stopped \
		$(IMAGE_NAME)
	@echo "waiting for the health probe"
	@for i in $$(seq 1 20); do \
		status=$$(docker inspect $(IMAGE_CONTAINER) --format '{{.State.Health.Status}}' 2>/dev/null); \
		[ "$$status" = "healthy" ] && { echo "container is healthy"; exit 0; }; \
		sleep 1; \
	done; \
	echo "ERROR: container did not become healthy"; docker logs $(IMAGE_CONTAINER) 2>&1 | tail -20; exit 1

image-stop:
	@docker rm -f $(IMAGE_CONTAINER) 2>/dev/null || echo "no container named $(IMAGE_CONTAINER)"

# Reports the facts that matter before trusting an image: which commit it came
# from, its size, and whether the binary is static and runs as a non-root user.
image-inspect:
	@echo "=== $(IMAGE_NAME) ==="
	@docker image inspect $(IMAGE_NAME) --format 'id={{.Id}} size={{.Size}} created={{.Created}}'
	@echo "--- binary ---"
	@docker run --rm --entrypoint sh $(IMAGE_NAME) -c \
		'ls -l /opt/agent-cluster/bin/agent-cluster-server; id'
	@echo "--- healthcheck ---"
	@docker image inspect $(IMAGE_NAME) --format '{{json .Config.Healthcheck}}'

image-clean:
	@docker image rm $(IMAGE_NAME) 2>/dev/null || echo "no image named $(IMAGE_NAME)"

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
