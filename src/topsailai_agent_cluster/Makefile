# Author: DawsonLin
# Purpose: Build, verify and operate the Agent Cluster locally.
#
# Production binaries are written to bin/ because scripts/start-local-cluster.sh
# loads them from there. The test-hooks variant stays in .tmp/artifacts/ so that
# building instrumented binaries never overwrites the ones a running cluster uses.

SHELL := /bin/bash

BIN_DIR := bin
TESTHOOKS_DIR := .tmp/artifacts
LAUNCHER := scripts/start-local-cluster.sh

SERVER_PKG := ./src/main/agent-cluster-server
ENDPOINT_PKG := ./src/main/agent-cluster-endpoint
CLI_PKG := ./src/main/agent-cluster-cli

.DEFAULT_GOAL := help

.PHONY: help build build-testhooks vet test bdd integration fmt \
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
	@echo "  test              run the unit test suite"
	@echo "  bdd               run the BDD feature suite"
	@echo "  integration       run the integration suite with test hooks"
	@echo "  fmt               format Go sources in place"
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

bdd:
	go test ./tests/bdd -count=1 -v

integration:
	go test -tags='integration testhooks' ./tests/integration -count=1

fmt:
	gofmt -w src internal

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
