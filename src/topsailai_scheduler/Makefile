# Makefile for the scheduler project.
#
# Every target is a thin wrapper around the Go toolchain so the same commands
# work locally and in CI. Build artifacts go to .tmp/ so the source tree stays
# clean.

# GO is overridable so a specific toolchain can be selected without editing.
GO ?= go
# GOTOOLCHAIN is pinned to local so a go.mod directive never downloads a
# different toolchain mid-build.
export GOTOOLCHAIN := local

# BIN is the built scheduler binary.
BIN := .tmp/topsailai_scheduler
# COVERPROFILE is the coverage output, kept out of the source tree.
COVERPROFILE := .tmp/coverage.out

.PHONY: all build test cover vet fmt check clean run

all: check

# build compiles the scheduler binary.
build:
	@mkdir -p .tmp
	cd src && $(GO) build -o ../$(BIN) ./main

# test runs every test with the race detector.
test:
	@mkdir -p .tmp
	cd src && $(GO) test ./... -race -count=1

# cover runs the tests and reports per-package coverage.
cover:
	@mkdir -p .tmp
	cd src && $(GO) test ./... -race -count=1 -coverprofile=../$(COVERPROFILE)
	cd src && $(GO) tool cover -func=../$(COVERPROFILE) | tail -1

# vet runs the static analyser.
vet:
	cd src && $(GO) vet ./...

# fmt reports files that are not gofmt-clean.
fmt:
	@cd src && out=$$(gofmt -l .); \
	if [ -n "$$out" ]; then echo "not gofmt-clean:"; echo "$$out"; exit 1; fi

# check is the full local gate.
check: fmt vet test

# run starts the daemon from the project root.
run: build
	./$(BIN) run

# clean removes build and test artifacts.
clean:
	rm -rf .tmp/topsailai_scheduler .tmp/coverage.out
