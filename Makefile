# TopsailAI Makefile
#
# Targets:
#   build-deb     - Build TopsailAI binary deb packages (core-agent + topsailai_data)
#   build-docker  - Build Docker image from the deb packages (Dockerfile.binary)
#   clean         - Remove build artifacts
# Environment:
#   OUTPUT_DIR    - deb output directory (default: build/output)
#   DOCKER_TAG    - docker image tag (default: topsailai:YYYYMMDD.N, auto-increment)
#   REQUIRE_NEW_SO- set to 1 to force recompilation (default: 0)

# Auto-detect project home as the directory containing this Makefile (portable)
PROJECT_HOME := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
# Absolute output dir based on PROJECT_HOME so dev-tools resolves it correctly.
# After a build, $(OUTPUT_DIR)/.deb/<pkg>/... holds the unpacked staging layout,
# which lets you inspect the packaged folder structure before install.
# Example: tree $(OUTPUT_DIR)/.deb/topsailai/TopsailAI/src | head
OUTPUT_DIR   ?= $(PROJECT_HOME)/build/output
# Docker image tag with date-based auto-increment (e.g. topsailai:20260812.1)
BUILD_DATE := $(shell date +%Y%m%d)
BUILD_SEQ := $(shell docker images --format '{{.Tag}}' topsailai 2>/dev/null | grep '^$(BUILD_DATE)\.' | sed 's/^$(BUILD_DATE)\.//' | sort -n | tail -1 | awk '{print $$1+1}')
ifeq ($(strip $(BUILD_SEQ)),)
BUILD_SEQ := 1
endif
DOCKER_TAG ?= topsailai:$(BUILD_DATE).$(BUILD_SEQ)
# REQUIRE_NEW_SO: 0 = reuse existing .so files (default, recommended)
#                 1 = force recompilation (debugging only)
# IMPORTANT: Always use REQUIRE_NEW_SO=0. If packaging fails, analyze the
#            root cause instead of setting this variable to work around it.
REQUIRE_NEW_SO ?= 0

.PHONY: build-deb build-docker clean help

## Build TopsailAI binary deb packages (core-agent + topsailai_data)
build-deb:
	@echo "==> Building TopsailAI deb packages..."
	@mkdir -p $(OUTPUT_DIR)
	@REQUIRE_NEW_SO=$(REQUIRE_NEW_SO) dev-tools deb-build-cython-py3 -p $(PROJECT_HOME) -o $(OUTPUT_DIR)
	@echo "==> Done. deb packages are in $(OUTPUT_DIR)/"
	@ls -lh $(OUTPUT_DIR)/*.deb

## Build Docker image from the deb packages (uses docker/Dockerfile.binary)
build-docker: build-deb
	@echo "==> Building Docker image $(DOCKER_TAG)..."
	@mkdir -p docker/deb-output
	@cp -f $$(ls -t $(OUTPUT_DIR)/topsailai-[0-9]*.deb | head -1) docker/deb-output/topsailai-1.0.deb
	@cp -f $$(ls -t $(OUTPUT_DIR)/topsailai-data-[0-9]*.deb | head -1) docker/deb-output/topsailai-data-1.0.deb
	@docker build -f docker/Dockerfile.binary -t $(DOCKER_TAG) .
	@echo "==> Done. Docker image $(DOCKER_TAG) built."

## Remove build artifacts
clean:
	@echo "==> Cleaning build artifacts..."
	@rm -rf $(OUTPUT_DIR)
	@rm -rf docker/deb-output
	@echo "==> Done."

## Show this help message
help:
	@echo "Usage:"
	@echo "  make <target>"
	@echo ""
	@echo "Targets:"
	@echo "  build-deb      Build TopsailAI binary deb packages (core-agent + topsailai_data)"
	@echo "  build-docker   Build Docker image from the deb packages (Dockerfile.binary)"
	@echo "  clean          Remove build artifacts"
	@echo "  help           Show this help message"
