# Provider CLI Protocol Version 1

This directory is the language-neutral contract between the Endpoint Generic CLI Adapter and an
independently built Provider CLI. The JSON Schemas define request, response and JSON Lines stream
frames. The Go DTOs and semantic validation live in `internal/providercli`.

## Process framing

A non-streaming invocation reads exactly one JSON request from standard input and writes exactly one
JSON response to standard output. A streaming invocation reads one request and writes one JSON object
per line: one `started` frame, zero or more ordered `record` frames, and one `end` frame. Provider
diagnostics belong on standard error and must never be mixed into standard output.

The Generic CLI Adapter records process exit status separately from the protocol response. It applies
these rules in order:

- Missing, malformed, oversized, uncorrelated or extra standard output is a protocol failure and can
  never prove success.
- Exit status zero plus one valid `ok: true` response is a successful invocation.
- A valid `ok: false` response is a Provider business failure even when the process exits zero. Its
  bounded error code, message and effect certainty remain evidence.
- A non-zero exit is an invocation failure. A valid `ok: false` response is still retained as Provider
  evidence; malformed output does not hide the bounded standard-error diagnostic.
- A non-zero exit paired with `ok: true` is a process/result conflict. It is never accepted as success,
  and its effect certainty is `unknown` because the two result channels disagree.
- Timeout, cancellation or process loss without a complete correlated response never upgrades an
  effect to success. After mutation begins, the effect remains `unknown` unless non-application is
  independently proven.

These precedence rules preserve a Provider's structured rejection without allowing an exit/result
conflict to become a false success.

## Deadline and cancellation

`deadline_at_ms` is an absolute UTC Unix timestamp in milliseconds and must be positive. The Generic
CLI Adapter rejects an already expired request before starting a process, then converts the remaining
budget to a local monotonic deadline. The Provider must not extend or reinterpret that deadline.

Cancellation is process-scoped. The Generic CLI Adapter terminates only the exact invocation process
group and waits for its cleanup; it never terminates processes by a broad name match. A Provider may
hand a durable Agent to an independent lifecycle owner before returning, but it must not report an
acknowledged effect before that custody handoff completes. Cleaning an invocation process group must
not terminate an Agent whose independent handoff already completed.

For a stream, cancellation asks the Provider process to stop. When the terminal channel remains
writable, the Provider emits one correlated `end` frame carrying a cancellation error. EOF without a
terminal frame is `stream_interrupted`, never a clean end.

## Authority boundary

Provider documents contain Provider observations and evidence only. Cluster resource IDs, command
IDs, request hashes, journal phases, command revisions and complete Cluster execution receipts are
Endpoint authority and are rejected at this seam.

## Size bounds

Request budgets are byte and record limits. JSON Schema `maxLength` counts Unicode characters rather
than encoded bytes, so it is only a portable shape bound for strings. Every implementation must also
enforce the constants in `internal/providercli` against UTF-8 encoded byte length. The Generic CLI
Adapter additionally enforces the request's standard-output, standard-error and record budgets while
reading the process; a structurally valid document cannot expand those transport budgets.
