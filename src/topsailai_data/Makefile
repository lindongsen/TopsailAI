# topsailai_data Makefile
# Project: topsailai_data
# Language: Go

# Binary and path configuration
BINARY_NAME := topsailai_data
CMD_PATH := ./cmd/topsailai_data
BIN_DIR := ./bin
BIN := $(BIN_DIR)/$(BINARY_NAME)

# Go configuration
GO := go
GOFLAGS :=

# Installation path configuration
GOPATH ?= $(shell $(GO) env GOPATH)
ifeq ($(GOPATH),)
    GOPATH := $(HOME)/go
endif
INSTALL_DIR := $(GOPATH)/bin

# Default target
.DEFAULT_GOAL := build

# Build the CLI binary
.PHONY: build
build:
	@mkdir -p $(BIN_DIR)
	$(GO) build $(GOFLAGS) -o $(BIN) $(CMD_PATH)

# Run all tests
.PHONY: test
test:
	$(GO) test ./... -count=1

# Run go vet
.PHONY: vet
vet:
	$(GO) vet ./...

# Format Go source files
.PHONY: fmt
fmt:
	$(GO) fmt ./...

# Clean build artifacts and test cache
.PHONY: clean
clean:
	rm -rf $(BIN_DIR)
	$(GO) clean -testcache

# Build and run the CLI with ARGS
.PHONY: run
run: build
	$(BIN) $(ARGS)

# Install binary to GOPATH/bin
.PHONY: install
install: build
	@mkdir -p $(INSTALL_DIR)
	cp $(BIN) $(INSTALL_DIR)/$(BINARY_NAME)

# Show help
.PHONY: help
help:
	@echo "Available targets:"
	@echo "  build   - Compile the CLI binary to bin/topsailai_data"
	@echo "  test    - Run go test ./... -count=1"
	@echo "  vet     - Run go vet ./..."
	@echo "  fmt     - Run go fmt ./..."
	@echo "  clean   - Remove bin/ and clear test cache"
	@echo "  run     - Build and run the CLI (use ARGS=...)"
	@echo "  install - Install binary to \$$(GOPATH)/bin"
	@echo "  help    - Show this help message"
