.PHONY: build build-testhooks vet test bdd integration fmt

build:
	mkdir -p .tmp/artifacts
	go build -o .tmp/artifacts/agent-cluster-server ./src/main/agent-cluster-server
	go build -o .tmp/artifacts/agent-cluster-endpoint ./src/main/agent-cluster-endpoint
	go build -o .tmp/artifacts/agent-cluster-tui ./src/main/agent-cluster-tui

vet:
	go vet ./...

test:
	go test -count=1 ./...

bdd:
	go test ./tests/bdd -count=1 -v

fmt:
	gofmt -w src internal

build-testhooks:
	mkdir -p .tmp/artifacts
	go build -tags=testhooks -o .tmp/artifacts/agent-cluster-server ./src/main/agent-cluster-server
	go build -tags=testhooks -o .tmp/artifacts/agent-cluster-endpoint ./src/main/agent-cluster-endpoint
	go build -tags=testhooks -o .tmp/artifacts/agent-cluster-tui ./src/main/agent-cluster-tui

integration:
	go test -tags='integration testhooks' ./tests/integration -count=1
