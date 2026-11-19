---
maintainer: AI
author: DawsonLin
status: planned
created: 2026-11-19
updated: 2026-11-19
---

# Resource-Efficient Read Test Cases

These cases verify `docs/resource-efficient-read-prd.md`. They separate portable correctness and ratio checks from absolute CPU and latency budgets that require the documented reference environment.

## Measurement rules

- Generate incompressible content so a transport cannot pass a byte budget by compressing a special fixture.
- Compare every completed destination byte for byte with the source.
- Record idle RSS before each run and report both absolute peak RSS and peak increase above idle.
- Measure process CPU, not only wall time. A sleeping process and a saturated process can have the same duration.
- Count protocol payload bytes separately from TLS, TCP, and WebSocket framing.
- Record operating system, CPU model, available memory, Go version, TLS mode, concurrency, and build revision.
- Use the same reference environment for absolute CPU and latency comparisons.
- Put generated files, logs, profiles, and reports under `.tmp/` and remove them after the evidence is recorded.
- Start long-running processes in tmux, record exact PIDs, and stop only those PIDs.

## Streaming and correctness

| ID | Level | Precondition | Action | Expected result |
|---|---|---|---|---|
| TC-RES-001 | Unit | An empty readable file | Read the whole file | Zero bytes are returned, the transfer terminates, and no unbounded extra request occurs |
| TC-RES-002 | Unit | A file one byte smaller than one chunk | Read the whole file | Every byte is returned once and the transfer ends after the final response |
| TC-RES-003 | Unit | A file exactly one chunk long | Read the whole file | Every byte is returned once and no contradictory truncation state causes an unbounded loop |
| TC-RES-004 | Unit | A file one byte larger than one chunk | Read the whole file | The final byte is returned exactly once in a second chunk |
| TC-RES-005 | Integration | A 16 MiB incompressible readable file | Read to a new destination | The destination is byte-identical and no whole-file buffer is retained |
| TC-RES-006 | Resource | A 256 MiB incompressible readable file | Read to a new destination while sampling all processes | Output is byte-identical and each process stays within the PRD memory budget |
| TC-RES-007 | Integration | A read with nonzero offset and bounded length crossing a chunk boundary | Read the requested range | The destination equals the exact source slice, with no byte before or after the requested range |
| TC-RES-008 | Integration | A source fails after at least one chunk and an existing destination is present | Read with replacement allowed | The existing destination remains unchanged and the command exits nonzero |
| TC-RES-009 | Integration | A transfer is cancelled after at least one chunk | Cancel the caller | The temporary output is removed with a logged cleanup result and unrelated files remain |

## CPU, memory, and wire cost

| ID | Level | Precondition | Action | Expected result |
|---|---|---|---|---|
| TC-RES-010 | Unit | A maximum-size file-content frame | Encode and decode it repeatedly | The frame remains within its configured cap and allocations are bounded by the frame budget |
| TC-RES-011 | Integration | A 16 MiB incompressible file and TLS disabled | Read the whole file while counting protocol bytes | Protocol bytes are no more than 1.10 times content bytes |
| TC-RES-012 | Resource | The documented reference environment and a 16 MiB file | Read the whole file while sampling CPU | Server and Node CPU remain within the PRD budgets |
| TC-RES-013 | Resource | Identical environment and 16 MiB and 256 MiB files | Read both sequentially | After subtracting idle baselines, each process's larger-file peak RSS is no more than 25% above the smaller-file increase |
| TC-RES-014 | Resource | A successful resource run | Persist its report | Report includes content bytes, protocol bytes, wall time, process CPU, peak RSS, throughput, concurrency, platform, TLS mode, and build revision |
| TC-RES-015 | Security | A transfer uses real credentials and a private scope path | Inspect logs and resource reports | No credential, proof, nonce, file content, or absolute scope path appears |

## Concurrency, fairness, and overload

| ID | Level | Precondition | Action | Expected result |
|---|---|---|---|---|
| TC-RES-016 | Resource | Eight authorized 16 MiB reads are active | Submit an authorized `file.stat` | The metadata request meets the PRD P95 latency budget and all reads remain exact |
| TC-RES-017 | Integration | One caller reaches its active-read limit and another caller remains below its limit | Start another read as the second caller | The second caller is admitted when Server and Node capacity remain available |
| TC-RES-018 | Integration | One Node reaches its active-read limit and another Node has capacity | Start a read on the second Node | The second Node's request is admitted independently |
| TC-RES-019 | Integration | Server-wide capacity is full | Submit another read beyond the bounded wait | The request receives the documented retryable overload response, not timeout, `internal`, or false success |
| TC-RES-020 | Integration | New work is refused for overload while active reads continue | Let active reads finish | Every admitted output remains byte-identical and no response contains another request's bytes |
| TC-RES-021 | Resource | Eight concurrent 16 MiB reads | Measure peak RSS and CPU | Resources remain within the documented concurrency budget and no process crashes or grows without bound |

## Compatibility and fail-closed behavior

| ID | Level | Precondition | Action | Expected result |
|---|---|---|---|---|
| TC-RES-022 | Integration | Server and Node share one efficient transport version | Perform an authorized read | The version is selected explicitly and the destination is byte-identical |
| TC-RES-023 | Integration | Server and Node have no common file transport version | Perform an authorized read | The operation is refused before content transfer with non-secret upgrade guidance |
| TC-RES-024 | Adversarial | Efficient transport is required and the peer offers only an older version | Perform an authorized read | No silent downgrade occurs |
| TC-RES-025 | Integration | Old and new peers are paired in every supported rollout order | Connect and perform control and file operations | Each documented pair either works in its declared mode or refuses explicitly; no frame is misinterpreted |
| TC-RES-026 | Compile | Windows target build | Compile all changed packages and tests | Compilation succeeds without platform-specific protocol divergence |

## Preserved security boundaries

| ID | Level | Precondition | Action | Expected result |
|---|---|---|---|---|
| TC-RES-027 | Adversarial | Invalid client proof | Request a file through the efficient path | Server refuses as unauthenticated before forwarding content |
| TC-RES-028 | Adversarial | Invalid Node proof | Request a file through the efficient path | Node refuses as unauthenticated and no content reaches the caller |
| TC-RES-029 | Adversarial | Authenticated caller without read permission | Request an existing file | Node refuses as denied and does not disclose content existence through an efficient-path difference |
| TC-RES-030 | Adversarial | Authorized caller supplies `..`, absolute, symlink escape, or denied-config alias | Request through the efficient path | The same path-fence refusal class applies and no outside bytes are transferred |
| TC-RES-031 | Adversarial | A valid proof is replayed | Retry it through the efficient path | The appropriate verifier rejects replay before content transfer |
| TC-RES-032 | Adversarial | Two reads are concurrent and their content differs | Reorder, duplicate, omit, or cross-route one binary chunk in a protocol probe | The receiver refuses the malformed stream and never publishes mixed output |

## Required execution layers

- Unit checks run with `go test` in colorless mode and include allocation-sensitive checks where stable.
- Integration checks use the real Server, Node, and HTTP/WebSocket boundaries.
- BDD scenarios in `docs/cases/resource-efficient-read.feature` cover observable acceptance behavior.
- Resource checks run as a separate maintained target so the ordinary unit loop stays fast while release evidence remains reproducible.
- Windows behavior is compiled on every supported host and exercised live on a real Windows host before final acceptance when filesystem or process behavior is involved.
