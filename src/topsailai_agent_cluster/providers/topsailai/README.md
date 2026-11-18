# TopsailAI Provider

The TopsailAI Provider is the production implementation of the Agent Cluster Adapter CLI protocol. It
receives one standard request, translates it into the installed TopsailAI business CLI, and returns
provider evidence. It is packaged as `agent-cluster-provider-topsailai` and installed independently of
the Endpoint.

## Workspace layout

```text
providers/topsailai/
├── README.md      # this document
├── project.yaml   # workspace metadata
├── Makefile       # build, vet, test and clean
├── go.mod         # module agent-cluster-provider-topsailai
├── go.sum
├── issues/        # provider-owned issue records
├── src/           # package main and its unit tests
└── tests/         # test artifacts this provider owns
    └── fixtures/
        └── topsailai_provider_conformance/main.go
```

`tests/` holds only artifacts this provider owns. The conformance fixture emulates the TopsailAI
business CLI, which is this provider's own dependency, so it belongs here rather than in the cluster's
`tests/` tree. It imports only the standard library, so it needs no cluster package and cannot drift
with the cluster's internal types. The cluster's own test doubles stay in the cluster, because they
assert the cluster contract rather than this provider's behaviour.

`go.mod` sits at the workspace root because a Go module root must be the workspace root. The package
and its tests live in `src/` because Go requires a test to live beside the package it tests.

## Build and test

```bash
make build     # .tmp/bin/agent-cluster-provider-topsailai
make vet
make test
make check     # vet, then test
make clean
```

Every generated file stays under `.tmp/`. The binary is written to `.tmp/bin/` rather than the
workspace root, because `go build .` in a module root drops an executable named after the module
beside `go.mod`.

## Source map

The package is one Go package, so the files are grouped by responsibility rather than by import
boundary:

| Area | Files | Responsibility |
|---|---|---|
| Entry point and framing | `main.go`, `codec.go`, `protocol.go` | read one request, validate the envelope, encode one response |
| Dispatch | `provider.go` | route a function to its handler, own the coded error vocabulary |
| Descriptor | `descriptor.go`, `platform_linux.go`, `platform_other.go` | advertise the truthful capability surface for this host |
| Discovery and reads | `read.go`, `resolve_digest.go`, `output.go`, `follow.go` | observe provider state, resolve a target, read and tail output |
| Queries | `query.go`, `model_current.go`, `tokenizer.go` | answer the closed query registry |
| Mutations | `mutation.go`, `mutation_argv.go`, `mutation_authority.go`, `mutation_control.go` | build provider argv, revalidate authority, apply one operation |
| Process custody | `runner.go`, `process_unix.go`, `process_other.go` | start the business CLI, bound it, clean up its exact process group |
| Validation | `folder.go` | reject an unsafe project path |

## Protocol behaviour

One request arrives on stdin as a single JSON document; one response leaves on stdout. A streaming
function writes JSON Lines with exactly one terminal frame. Diagnostics go to stderr and are never
parsed as a result. The request envelope is closed and decoded strictly, so an unknown field is a
protocol failure rather than an ignored value.

The provider returns provider evidence, never a cluster receipt. The Endpoint owns authorization, the
command journal, resource mapping and the complete receipt.

## Configuration

Configuration is local administrative configuration, read once at the process boundary:

| Variable | Purpose |
|---|---|
| `AGENT_CLUSTER_TOPSAILAI_EXECUTABLE` | the TopsailAI business CLI this provider invokes |
| `AGENT_CLUSTER_TOPSAILAI_CONTROL_ACTIONS` | the control action catalog this provider advertises |

A remote request can never supply an executable, an argv template, a configuration path or an
environment override.

## Guards in this workspace

| Guard | Property |
|---|---|
| `src/catalog_shipped_test.go` | the shipped control action catalog parses and names only actions this provider serves |
| `src/workspace_list_flag_guard_test.go` | every flag this provider sends on a `workspace list` argv is registered by the business CLI |
| `src/instruction_argv_guard_test.go` | the instruction argv has exactly one production spelling |
| `src/platform_gate_test.go` | `agent.stop` is advertised only where the host can stop, and the gate is not a package global |
| `src/mutation_authority_test.go` | authority is revalidated in the same path that applies the mutation |
| `src/read_test.go`, `src/read_unattributed_test.go` | discovery and reads fail closed and emit no cluster identity |

A guard that reads a file outside this workspace resolves it by module identity, never by counting
directory levels. Two kinds of external file are read:

- Cluster project files, such as `conf/control-actions.conf.example`, resolved by walking up to the
  `go.mod` that declares `module topsailai_agent_cluster`.
- TopsailAI project files, such as the business CLI source, resolved as a sibling of the cluster
  project.

A depth is a position, so a guard that reads the wrong file passes while proving nothing. The
resolver lives in `src/repopath_test.go`.

## What this provider must not do

- It must not import a cluster package. The module boundary makes that impossible to build.
- It must not mint, persist or interpret a cluster resource ID. It returns provider-private keys and
  generation evidence; the Endpoint maps them.
- It must not decide cluster authorization or journal state. It revalidates the provider generation it
  was given, which is a provider fact, not a cluster decision.
- It must not read provider files to answer a read the business CLI can answer. The business CLI is
  the provider's own interface, and a direct file read would bypass the contract it implements.

## How the cluster builds it

The cluster never imports this module. It builds `providers/topsailai/src` as a separate module:

| Consumer | Purpose |
|---|---|
| `make test-provider-topsailai-conformance` | drive the conformance suite against this executable |
| `scripts/make-deb.sh --role provider` | build the packaged artifact |

The packaged payload path carries the package version, so installing a new version never overwrites
the bytes an Adapter is currently running and a rollback is a path change rather than a rebuild.
