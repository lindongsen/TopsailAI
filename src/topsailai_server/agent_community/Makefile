# Makefile for AI-Agent Community Server (ACS)
# Project: github.com/topsailai/agent-community

# Variables
PROJECT_NAME := agent-community
SERVER_BINARY := bin/acs-server
CLI_BINARY := bin/acs-cli
GO := go
GOFLAGS := -v

# Default target
.PHONY: all
all: build

# Build both server and CLI
.PHONY: build
build: build-server build-cli

# Build server binary
.PHONY: build-server
build-server:
	@echo "Building server..."
	@mkdir -p bin
	$(GO) build $(GOFLAGS) -o $(SERVER_BINARY) ./cmd/server

# Build CLI binary
.PHONY: build-cli
build-cli:
	@echo "Building CLI..."
	@mkdir -p bin
	$(GO) build $(GOFLAGS) -o $(CLI_BINARY) ./cmd/cli

# Run unit tests
.PHONY: test
test:
	@echo "Running unit tests..."
	$(GO) test -v -race ./...

# Run integration tests (Python)
.PHONY: test-integration
test-integration:
	@echo "Running integration tests..."
	@cd tests/integration && python3 -m pytest --color=no -v

# Run database migrations (up)
.PHONY: migrate-up
migrate-up:
	@echo "Running database migrations (up)..."
	$(GO) run ./cmd/migrate up

# Rollback database migrations (down)
.PHONY: migrate-down
migrate-down:
	@echo "Rolling back database migrations (down)..."
	$(GO) run ./cmd/migrate down

# Clean build artifacts
.PHONY: clean
clean:
	@echo "Cleaning build artifacts..."
	rm -rf bin/
	$(GO) clean

# Run server locally
.PHONY: run
run: build-server
	@echo "Starting ACS server..."
	./$(SERVER_BINARY)

# Run server with hot reload (requires air)
.PHONY: dev
dev:
	@echo "Starting ACS server in dev mode..."
	@which air > /dev/null || (echo "Installing air..." && go install github.com/cosmtrek/air@latest)
	air

# Format Go code
.PHONY: fmt
fmt:
	@echo "Formatting Go code..."
	$(GO) fmt ./...

# Run linter (requires golangci-lint)
.PHONY: lint
lint:
	@echo "Running linter..."
	@which golangci-lint > /dev/null || (echo "Installing golangci-lint..." && go install github.com/golangci/golangci-lint/cmd/golangci-lint@latest)
	golangci-lint run ./...

# Generate Go module dependencies
.PHONY: deps
deps:
	@echo "Downloading dependencies..."
	$(GO) mod download
	$(GO) mod tidy

# Docker build
.PHONY: docker-build
docker-build:
	@echo "Building Docker image..."
	docker build -t $(PROJECT_NAME):latest .

# Docker run
.PHONY: docker-run
docker-run:
	@echo "Running Docker container..."
	docker run --rm -p 7370:7370 $(PROJECT_NAME):latest

# Help
.PHONY: help
help:
	@echo "ACS Makefile targets:"
	@echo "  build            - Build server and CLI binaries"
	@echo "  build-server     - Build server binary only"
	@echo "  build-cli        - Build CLI binary only"
	@echo "  test             - Run unit tests"
	@echo "  test-integration - Run integration tests (Python)"
	@echo "  migrate-up       - Run database migrations (up)"
	@echo "  migrate-down     - Rollback database migrations (down)"
	@echo "  clean            - Clean build artifacts"
	@echo "  run              - Run server locally"
	@echo "  dev              - Run server with hot reload (requires air)"
	@echo "  fmt              - Format Go code"
	@echo "  lint             - Run linter (requires golangci-lint)"
	@echo "  deps             - Download and tidy Go module dependencies"
	@echo "  docker-build     - Build Docker image"
	@echo "  docker-run       - Run Docker container"
	@echo "  help             - Show this help message"
