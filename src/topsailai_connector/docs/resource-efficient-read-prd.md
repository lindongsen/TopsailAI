---
maintainer: AI
author: DawsonLin
status: draft
created: 2026-11-19
updated: 2026-11-19
---

# Resource-Efficient File Read Product Requirements

## Document status

This PRD defines the product requirement that `file.read`, especially whole-file reads through `-o`, should use as few local and cloud resources as practical while preserving correctness, security, and cross-platform behavior.

The supporting measured problem record is `issues/issue-large-read-is-cpu-bound-and-double-base64.md`. This PRD states the desired outcome and acceptance boundaries; it deliberately does not prescribe a transport encoding or protocol implementation.

## Overview

### Background and motivation

The Connector may read files from a personal computer through a cloud Server. A read must not make the Node noticeably compete with the owner's normal work, and one caller must not consume disproportionate Server capacity. The current whole-file path keeps memory bounded, but measured large reads spend almost the full transfer time on Server CPU and expand data substantially on the wire. Existing automated tests prove correctness only with fixtures up to 1 MiB and do not detect CPU, memory, network, or throughput regressions.

The product requirement is therefore not maximum benchmark throughput at any cost. It is predictable, bounded, and economical resource use: stream data in bounded chunks, avoid redundant work and copies, keep concurrency fair, and degrade safely under pressure.

### Product goals

- Keep Node memory bounded independently of file size.
- Keep Server and CLI memory bounded independently of file size.
- Minimize CPU work, allocations, copies, and wire bytes per content byte.
- Prevent one large read or one caller from starving unrelated Nodes and requests.
- Preserve byte-for-byte output, path-fence enforcement, authentication, replay protection, and default-deny authorization.
- Support Linux, macOS, and Windows with the same observable behavior.
- Make resource use measurable in automated regression checks.
- Prefer safe resource ceilings over unbounded concurrency or maximum peak throughput.

### Product non-goals

- Guaranteeing a fixed transfer speed on every disk, network, or host.
- Loading a whole file into memory to improve benchmark throughput.
- Weakening authentication, replay protection, path validation, or permission checks.
- Adding compression by default when it may increase CPU or expand already-compressed content.
- Providing resumable cross-session downloads in this release.
- Optimizing `file.list` or `file.stat` beyond ensuring they remain responsive during a large read.

### Success measures

A release meets this PRD when all of the following are demonstrated on the reference Linux environment and checked for behavioral compatibility on Windows:

- A 256 MiB whole-file read produces byte-identical output.
- Peak RSS of Node, Server, and CLI does not grow proportionally with file size. When file size increases from 16 MiB to 256 MiB, each process's peak RSS increase is no more than 25% after subtracting its idle baseline.
- One active read holds no more than two configured content chunks per process, excluding fixed process/runtime overhead.
- Steady-state protocol bytes are no more than 1.10 bytes per content byte for files of at least 16 MiB, excluding TLS, TCP, and WebSocket framing.
- The Server uses no more than 0.25 CPU-seconds per 16 MiB transferred on the reference environment, excluding TLS. This threshold is a regression budget, not a portability promise.
- The Node uses no more than 0.10 CPU-seconds per 16 MiB transferred on the reference environment, excluding filesystem time.
- Eight concurrent 16 MiB reads complete with correct output; Server and Node peak RSS remain within the documented concurrency budget, and a simultaneous small `file.stat` request completes within 500 ms at the 95th percentile on the reference environment.
- The standard test workflow records size, wall time, process CPU, peak RSS, transferred protocol bytes, throughput, concurrency, and exact build revision.
- A resource-budget regression fails the performance check or is explicitly approved with updated measurements and rationale; it cannot silently pass because functional output remains correct.

The reference environment must record CPU model, available memory, Go version, operating system, and whether TLS is enabled. Absolute CPU and latency thresholds are compared only on comparable environments; ratios and bounded-memory properties apply everywhere.

## Personas

| Persona | Identity | Core goal | Main pain point |
|---|---|---|---|
| Node owner | Person running the Node on a personal computer | Share allowed files without slowing normal local work | A remote large read can compete for CPU, memory, disk, and network resources |
| Server operator | Person operating the cloud Server | Serve multiple Nodes and callers predictably | One expensive transfer can consume a Server core and reduce capacity for everyone |
| CLI user or automation owner | Person downloading a permitted file | Receive the complete, exact file without managing chunks manually | Resource pressure can make a download slow, fail part way, or disturb other users |
| Performance reviewer | Person accepting protocol and runtime changes | Detect resource regressions with reproducible evidence | Existing correctness tests do not observe CPU, RSS, wire expansion, or fairness |

## User stories

### Node owner

- **US-001:** As a Node owner, I want large reads to use bounded memory so sharing a large file cannot exhaust my machine.
- **US-002:** As a Node owner, I want the Node to avoid redundant encoding and copying so remote reads do not noticeably consume my CPU.
- **US-003:** As a Node owner, I want per-Node resource limits so several callers cannot starve my local work.

### Server operator

- **US-004:** As a Server operator, I want transfer cost to scale close to the actual content size so Server capacity is not spent on avoidable transformations.
- **US-005:** As a Server operator, I want bounded and fair concurrency so one caller or Node cannot monopolize the Server.
- **US-006:** As a Server operator, I want resource telemetry and regression budgets so capacity changes are visible before release.

### CLI user or automation owner

- **US-007:** As a CLI user, I want a whole-file read to stream incrementally so the CLI does not hold the whole file in memory.
- **US-008:** As a CLI user, I want the downloaded bytes to match the source exactly even when reads are chunked or throttled.
- **US-009:** As an automation owner, I want overload to produce a clear retryable response rather than a timeout, partial success, or process crash.

### Performance reviewer

- **US-010:** As a performance reviewer, I want repeatable large-file and concurrent-read checks so changes can be compared with a known baseline.
- **US-011:** As a performance reviewer, I want resource budgets expressed independently of one implementation so the team can improve the protocol without rewriting the requirement.
- **US-012:** As a performance reviewer, I want security and correctness regression tests to run with resource checks so optimization cannot bypass an existing boundary.

## User journey

1. A Node owner grants a read permission to a scope and continues using the personal computer normally.
2. A CLI caller requests a whole file with `-o`.
3. The Node reads and sends bounded chunks without loading the whole file or doing redundant per-byte transformations.
4. The Server forwards data with bounded buffering and fair scheduling across callers and Nodes.
5. The CLI writes incrementally to a temporary destination and publishes only a complete, verified result.
6. If a resource limit is reached, the system rejects or slows additional work predictably without corrupting an active transfer.
7. Release checks compare CPU, RSS, wire bytes, throughput, and fairness with the accepted baseline.

## Functional requirements

| ID | Feature | Stories | Description | Inputs | Outputs and interaction |
|---|---|---|---|---|---|
| F-001 | Bounded streaming read | US-001, US-007, US-008 | Transfer file content incrementally with a bounded amount of content buffered in each process | File path, offset, optional length, configured chunk budget | Ordered byte stream and completion status; no whole-file buffering |
| F-002 | Resource-efficient transport | US-002, US-004, US-011 | Carry file bytes with minimal transformation, copying, and protocol expansion | Authenticated read result and content chunk | Protocol representation within the wire and CPU budgets |
| F-003 | Fair bounded concurrency | US-003, US-005, US-009 | Bound concurrent read work by caller, Node, and Server and preserve capacity for small requests | Active request counts and configured limits | Admission, bounded queueing, or explicit retryable refusal |
| F-004 | Atomic complete output | US-007, US-008, US-009 | Keep the existing complete-destination property while streaming | Destination, force decision, incoming chunks | Complete byte-identical destination or unchanged previous destination |
| F-005 | Resource observability | US-006, US-010 | Measure and report per-run resource cost without exposing paths, content, credentials, proofs, or nonces | Process metrics and transfer counters | CPU, RSS, bytes, duration, throughput, concurrency, build revision |
| F-006 | Automated resource regression check | US-006, US-010, US-012 | Exercise representative single and concurrent reads and enforce accepted budgets | Generated test files and controlled reference environment | Pass/fail report with raw measurements and comparison baseline |
| F-007 | Safe overload behavior | US-003, US-005, US-009 | Degrade predictably when limits are reached | Capacity state and incoming request | Existing work remains correct; new work waits within a bound or receives a retryable refusal |
| F-008 | Optional adaptive tuning | US-001, US-004 | Allow later tuning of chunk and concurrency budgets within documented safe ranges | Operator configuration | Validated bounded settings with safe defaults |
| F-009 | Versioned compatible rollout | US-009, US-011, US-012 | Negotiate a resource-efficient transport without silently downgrading security or misreading frames | Peer capability and protocol version | Compatible mode selection or explicit refusal with upgrade guidance |

## Non-functional requirements

| Dimension | Requirement |
|---|---|
| Resource efficiency | Memory is bounded by chunk and concurrency budgets, not by file size. Avoid redundant encoding, decoding, allocation, and copying. |
| Performance | Meet the CPU, wire-expansion, latency, and throughput regression budgets in Success measures. Protect small-request latency during large transfers. |
| Capacity | Define explicit per-read, per-caller, per-Node, and Server-wide limits. Defaults must be safe without operator tuning. |
| Correctness | Output is byte-identical, ordered, neither duplicated nor omitted, including exact chunk boundaries and final partial chunks. |
| Security | Every request remains authenticated and replay-protected; Node policy remains the only authority; no optimization bypasses the path fence or secret-handling rules. |
| Reliability | A mid-transfer failure never publishes a partial destination. Overload never crashes a process or produces false success. |
| Compatibility | Linux, macOS, and Windows expose the same CLI behavior and error classification. Protocol changes are versioned and never silently reinterpret an incompatible frame. |
| Observability | Resource metrics contain counts and public identifiers only; they exclude file content, absolute scope paths, credentials, proofs, and nonces. |
| Maintainability | Resource limits and baselines have one documented source of truth. A protocol change updates the API, permission design, skills, and tests together. |

## Functional dependencies

```text
F-001 Bounded streaming read
  ├── F-002 Resource-efficient transport
  │     └── F-009 Versioned compatible rollout
  └── F-004 Atomic complete output

F-003 Fair bounded concurrency
  └── F-007 Safe overload behavior

F-005 Resource observability
  └── F-006 Automated resource regression check

F-008 Optional adaptive tuning depends on measured results from F-005 and F-006.
Security and correctness requirements apply to F-001 through F-009.
```

## MoSCoW priority

| ID | Feature | Priority | Reason |
|---|---|---|---|
| F-001 | Bounded streaming read | Must | Whole-file buffering would violate the core low-resource requirement |
| F-002 | Resource-efficient transport | Must | Current avoidable per-byte transformations dominate CPU and wire cost |
| F-003 | Fair bounded concurrency | Must | One efficient read is insufficient if many reads can still starve the host |
| F-004 | Atomic complete output | Must | Resource optimization cannot trade away output correctness |
| F-005 | Resource observability | Must | A low-resource claim without measurements cannot be accepted or protected |
| F-006 | Automated resource regression check | Should | Repeatable enforcement is required for durable quality, but can follow the first transport correction |
| F-007 | Safe overload behavior | Should | Capacity limits need predictable user-visible behavior; conservative refusal can temporarily substitute |
| F-008 | Optional adaptive tuning | Could | Safe defaults are preferable; tuning is useful only after real workloads are understood |
| F-009 | Versioned compatible rollout | Should | A transport improvement must fail clearly across incompatible peers and preserve security during upgrade |
| — | Compression enabled by default | Won't | It can consume CPU and expand already-compressed files, conflicting with the primary goal |
| — | Resumable cross-session download | Won't | Valuable for reliability but adds state and complexity beyond this resource-efficiency release |

Must features are 5 of 9 planned features, or 55.6%.

## Release recommendation

### Initial resource-efficiency release

Deliver F-001 through F-005 and the minimum negotiation and refusal behavior from F-009. Preserve current CLI behavior while reducing per-byte CPU and wire expansion. Do not expose tuning flags until safe ranges are measured.

### Follow-up hardening release

Deliver F-006, F-007, and the complete rollout coverage from F-009, including reference-environment regression checks, fairness checks, explicit overload responses, and mixed-version tests.

### Later evaluation

Consider F-008 only when production evidence shows that one default cannot serve both low-resource personal computers and high-capacity Server installations.

## Acceptance criteria

### F-001 Bounded streaming read

**AC-F001-01: Large read keeps bounded memory**\
Given the same Node, Server, and CLI read a 16 MiB file and a 256 MiB file sequentially\
When peak RSS is measured after subtracting each process's idle baseline\
Then each process's peak RSS increase for the larger file is no more than 25% above the smaller-file increase.

**AC-F001-02: Final partial chunk is preserved**\
Given a file whose size is an exact chunk plus one byte\
When the CLI reads the whole file\
Then the destination contains every source byte exactly once and reports success.

**AC-F001-03: Empty and exact-boundary files terminate**\
Given an empty file and a file exactly one configured chunk long\
When each is read as a whole file\
Then both operations terminate without an extra unbounded loop and produce byte-identical output.

### F-002 Resource-efficient transport

**AC-F002-01: Wire expansion stays within budget**\
Given a file of at least 16 MiB containing incompressible data\
When it is transferred without TLS\
Then steady-state protocol bytes excluding TCP and WebSocket framing do not exceed 1.10 times the content bytes.

**AC-F002-02: CPU stays within the reference budget**\
Given the documented reference environment and one 16 MiB read\
When process CPU time is measured\
Then Server CPU is at most 0.25 seconds and Node CPU is at most 0.10 seconds, excluding TLS and filesystem time.

**AC-F002-03: Security gates remain intact**\
Given an invalid proof, an unauthorized scope, or an escaping path\
When the optimized transport receives the request\
Then it returns the same refusal class as the current protected path and transfers no file content.

### F-003 Fair bounded concurrency

**AC-F003-01: Small requests remain responsive**\
Given eight concurrent 16 MiB reads are active\
When an authorized caller submits `file.stat`\
Then its 95th-percentile response time is no more than 500 ms on the reference environment.

**AC-F003-02: Per-Node work is bounded**\
Given one Node has reached its configured active-read limit\
When another read is submitted to that Node\
Then the request waits only within the documented bound or receives an explicit retryable refusal, and active reads continue correctly.

**AC-F003-03: One caller cannot monopolize capacity**\
Given one caller submits enough reads to reach its limit and another caller submits one valid read\
When Server capacity remains available\
Then the second caller's request is admitted independently of the first caller's excess work.

### F-004 Atomic complete output

**AC-F004-01: Successful destination is complete**\
Given a successful whole-file read\
When the destination becomes visible at its requested path\
Then it is byte-identical to the source.

**AC-F004-02: Failed transfer preserves an existing destination**\
Given an existing destination and `--force` is used\
When the transfer fails after at least one chunk\
Then the previous destination remains unchanged and no partial destination is published.

**AC-F004-03: Temporary output is cleaned up**\
Given a failed or cancelled transfer\
When the CLI exits\
Then its temporary output is removed with a logged cleanup result and unrelated files remain untouched.

### F-005 Resource observability

**AC-F005-01: Metrics describe the transfer**\
Given a completed or failed large read\
When resource evidence is recorded\
Then it includes content bytes, protocol bytes, wall time, process CPU, peak RSS, throughput, concurrency, outcome, platform, and build revision.

**AC-F005-02: Metrics contain no sensitive values**\
Given a transfer uses real credentials and a private scope path\
When metrics and logs are inspected\
Then they contain no credentials, proofs, nonces, file content, or absolute scope path.

**AC-F005-03: Measurements identify their environment**\
Given two resource reports are compared\
When their environments are not comparable\
Then the report makes the difference visible and does not present an absolute threshold comparison as a regression verdict.

### F-006 Automated resource regression check

**AC-F006-01: Standard representative sizes are exercised**\
Given the resource-check workflow runs\
When it reaches the file-read checks\
Then it measures at least empty, exact-chunk, 16 MiB, and 256 MiB reads and verifies byte identity.

**AC-F006-02: Concurrent behavior is exercised**\
Given the resource-check workflow runs\
When it reaches the concurrency checks\
Then it measures eight concurrent 16 MiB reads plus one small metadata request and reports fairness and peak resources.

### F-007 Safe overload behavior

**AC-F007-01: Overload is explicit**\
Given a configured capacity limit is reached\
When another request cannot be admitted within the bound\
Then it receives a documented retryable refusal rather than a timeout, `internal` error, false success, or process crash.

**AC-F007-02: Active work remains correct**\
Given overload causes new work to be refused\
When already-admitted reads finish\
Then their output remains byte-identical and no request receives another request's bytes.

### F-008 Optional adaptive tuning

**AC-F008-01: Unsafe values are refused**\
Given an operator configures a chunk or concurrency value outside the documented safe range\
When the process starts\
Then startup fails with a message naming the invalid public setting and no secret value.

### F-009 Versioned compatible rollout

**AC-F009-01: Compatible peers select the efficient transport**\
Given the Server and Node both advertise the same supported resource-efficient transport version\
When a file read begins\
Then they select that version explicitly and meet the same authentication, authorization, and output requirements.

**AC-F009-02: Incompatible peers fail clearly**\
Given the Server and Node have no mutually supported transport version\
When a file read is attempted\
Then the operation is refused before file content is transferred and the public error identifies the required upgrade without exposing credentials or local paths.

**AC-F009-03: No silent security downgrade**\
Given an optimized transport version is configured as required\
When a peer offers only an older transport\
Then the connection or operation is refused rather than silently choosing a mode with weaker authentication, replay protection, or path enforcement.

## Assumptions and constraints

### Assumptions

- The Node commonly runs on a personal computer whose resources are shared with interactive user workloads.
- Large files may be hundreds of MiB or several GiB, while the expected number of simultaneous callers per Node remains small.
- The Server may route multiple Nodes and therefore needs fairness across both caller and Node boundaries.
- TLS remains the confidentiality layer and may add separate CPU and wire overhead.

### Constraints

- Node policy remains the only source of scope and permission decisions.
- The Server never receives a Node credential secret and never stores proof material beyond the request.
- Windows remains supported in the same release as Linux and macOS.
- Existing `file.read`, `--offset`, `--length`, and `-o` user behavior must remain compatible unless a separately approved API change says otherwise.
- The CLI's complete-destination property must remain: partial data is never published as a successful destination.
- Resource limits have safe defaults; ordinary use must not require tuning.

### Risks

| Risk | Impact | Probability | Mitigation |
|---|---|---|---|
| A lower-CPU transport changes the wire contract | Mixed-version Nodes and Servers may fail to communicate | High | Version the capability, define compatibility behavior, and test mixed-version pairs before rollout |
| Larger chunks reduce request overhead but increase per-request memory and latency | Small requests may wait behind a large chunk | Medium | Choose a measured default and enforce fairness rather than maximizing chunk size |
| Concurrency limits reject legitimate bursts | Automation receives temporary failures | Medium | Use explicit retryable refusals, bounded waiting, and documented limits |
| Performance thresholds depend on hardware | Healthy changes may fail on a slower host | High | Separate portable ratio/boundedness checks from reference-environment absolute budgets |
| Compression appears to save bandwidth but burns CPU | The primary resource goal regresses | Medium | Keep compression off by default and require workload-specific evidence before adding it |
| Optimizing copies bypasses an authentication or fence boundary | Unauthorized content disclosure | Low but severe | Run security and adversarial suites on every optimized transport path |

## Open questions

- [ ] Is the primary operational priority Node impact, Server capacity, or both equally? This draft protects the personal-computer Node first and treats Server efficiency as equally required for release acceptance.
- [ ] Should overload wait in a short bounded queue, or should it fail immediately with a retryable response?
- [ ] What hardware and TLS mode should become the official reference environment for absolute CPU and latency budgets?
- [ ] Must a new transport support rolling upgrades between old and new Server/Node versions, or is coordinated upgrade acceptable?
- [ ] Should operators receive one high-level resource profile such as `low`, `balanced`, and `throughput`, or only safe automatic defaults?

## Recommended product decisions

- Protect the Node first. It runs on a person's machine; a remote read should be a background workload, not an interactive competitor.
- Keep memory bounded and predictable even if a benchmark could run faster by buffering more.
- Remove redundant representation work before increasing chunk size. A larger chunk reduces request count but does not solve avoidable per-byte CPU or wire expansion.
- Add fairness before exposing high concurrency. A global limit alone does not stop one caller or Node from consuming every slot.
- Treat resource evidence as a release artifact. Correct bytes with unmeasured CPU and RSS are not sufficient acceptance for this requirement.
- Do not enable compression by default. Consider it later only for known compressible workloads and only when total CPU, latency, and wire cost improve together.
