# Provider workspaces

Each directory here is an independent project workspace, not a package folder of the cluster
repository. A provider implements the Adapter CLI protocol defined by Agent Cluster, is built and
tested on its own, and is packaged as its own artifact.

```text
providers/
├── README.md      # this convention
├── mock/          # test-only reference provider and fault injector
└── topsailai/     # production provider that drives the TopsailAI business CLI
```

## Why each provider is a workspace

The cluster is the abstraction layer and a provider is one implementation of it. The two have
separate build metadata, dependencies, versions, tests and release artifacts, so a provider must be
readable, buildable and testable without reading the cluster Makefile. Treating a provider as a bare
package directory hides that independence: the only way to learn how to build it was to find the
cluster target that happened to invoke it.

## The layout every provider workspace follows

```text
<provider>/
├── README.md      # what this provider is, how to build, test and package it
├── project.yaml   # workspace metadata: identity, language, owning project
├── Makefile       # this workspace's single build and test entry point
├── go.mod         # module root, so the workspace root is the module root
├── go.sum         # when the module has dependencies
├── issues/        # provider-owned issue records, when the provider has any
└── src/           # package main sources and their unit tests
```

Two rules decide this shape:

- `go.mod` stays at the workspace root, because a Go module root must be the workspace root. A
  module nested one level deeper would make the workspace root a directory that Go does not know
  about.
- Unit tests stay beside the source in `src/`, because Go requires a test to live in the package
  directory it tests. This is the one place where the project structure convention's `tests/unit/`
  layout does not apply, and it applies to every Go package in this repository.

No `docs/` directory is created. The cluster defines the contract, and
`docs/agent-cluster-adapters.md` is the only place provider detail belongs. A provider-side copy of
that material would be a second source of truth for the same facts.

## Rules a provider workspace must keep

- Build and test through its own `Makefile`. A component-level or larger-scope run goes through a
  `make` target, never an ad-hoc `go build` or `go test` invocation, so the package path, the build
  tags and the working directory live in one place.
- Write build output and temporary files under the workspace's own `.tmp/`, never into the source
  directory or the workspace root.
- Never import a cluster package. The module boundary makes that impossible to build, and each
  provider asserts the absence rather than assuming it.
- Resolve a file outside the workspace by module identity, never by counting directory levels. A
  depth is a position, and a guard that reads the wrong file passes while proving nothing.
- Keep provider-native command names, flags, files and record formats inside the provider. They must
  never appear in the cluster protocol, a Server route, a stored document or a CLI help body.

## How the cluster reaches a provider

The cluster never imports a provider. It builds the provider's `./src` package as a separate module
and invokes the resulting executable through the Adapter CLI protocol:

| Consumer | What it builds |
|---|---|
| `make test-conformance` | `providers/mock/src` |
| `make test-provider-topsailai-conformance` | `providers/topsailai/src` |
| `scripts/make-deb.sh --role provider` | `providers/<type>/src` |
| `tests/harness` and `tests/integration` | `providers/mock/src` |

A provider is therefore reachable from the cluster only through its executable and its protocol, and
its internal layout is its own business.
