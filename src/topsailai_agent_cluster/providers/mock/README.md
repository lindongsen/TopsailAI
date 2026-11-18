# Mock Provider

The Mock Provider is a test-only implementation of the Agent Cluster Adapter CLI protocol. It serves
two purposes: a readable conforming reference for the protocol, and a deterministic fault injector
that the conformance, BDD and integration suites drive through the real process boundary.

It is never packaged and never deployed. `providers/topsailai` is the production provider.

## Workspace layout

```text
providers/mock/
├── README.md      # this document
├── project.yaml   # workspace metadata
├── Makefile       # build, vet, test and clean
├── go.mod         # module agent-cluster-provider-mock
└── src/           # package main and its unit tests
```

`go.mod` sits at the workspace root because a Go module root must be the workspace root. The package
and its tests live in `src/` because Go requires a test to live beside the package it tests.

## Build and test

```bash
make build     # .tmp/bin/agent-cluster-provider-mock
make vet
make test
make check     # vet, then test
make clean
```

Every generated file stays under `.tmp/`. The binary is written to `.tmp/bin/` rather than the
workspace root, because `go build .` in a module root drops an executable named after the module
beside `go.mod`.

## Protocol behaviour

One request arrives on stdin as a single JSON document; one response leaves on stdout. A streaming
function writes JSON Lines with exactly one terminal frame. Diagnostics go to stderr and are never
parsed as a result.

The mock advertises and answers the same operation surface, so an operation that is advertised but
not answered cannot pass unnoticed. A missing entry is a deliberate rejection rather than a silent
success.

## Fault injection

A fault is selected by local launch configuration only: an argv flag, or the environment variable the
conformance suite uses when it launches the mock directly. A remote request can never select a fault
mode, because the request envelope is closed and decoded strictly. This is asserted by a guard rather
than assumed, so a fault field added to the envelope fails the suite.

## What the mock must not do

- It must not import a cluster package. The module boundary makes that impossible to build, and
  `src/module_boundary_guard_test.go` asserts the absence so a relaxed boundary cannot reintroduce it.
- It must not be packaged. `scripts/make-deb.sh` builds only the provider type it is asked for, and
  the mock is not a provider type.
- It must not answer a read without recording the invocation when a scenario counts provider calls. A
  read that answers without leaving a record is indistinguishable from a read the cluster answered
  from its own cache.

## How the cluster builds it

The cluster never imports this module. It builds `providers/mock/src` as a separate module:

| Consumer | Purpose |
|---|---|
| `make test-conformance` | drive the conformance suite against this executable |
| `tests/harness` | start a real Endpoint with this provider configured |
| `tests/integration` | exercise replace, rehome and lifecycle paths |
| `tests/manual/live-tmux` | bounded manual sweeps |

## Guards in this workspace

| Guard | Property |
|---|---|
| `src/module_boundary_guard_test.go` | no cluster import, own module, no replace directive, root module does not depend on the mock |
| `src/watch_scope_test.go` | the protocol admits `watch` while this mock deliberately does not serve it |
| `src/inspect_fidelity_test.go` | inspection answers for the exact target it was asked about |
| `src/resolve_test.go` | resolve translates a handle without deciding existence |
| `src/main_test.go` | the advertised operation surface and its versions |

A guard that reads a file outside this workspace resolves it by module identity, never by counting
directory levels. A depth is a position, so a guard that reads the wrong file passes while proving
nothing.
