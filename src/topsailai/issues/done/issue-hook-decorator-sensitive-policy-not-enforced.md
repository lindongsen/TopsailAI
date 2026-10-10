---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
status: resolved
---
# Decorator sensitive-field policy is not enforced

## Review finding

`hooks/hook_point_decorator.py::_view()` exposes a shallow read-only mapping of every live bound argument and the live return object to `payload_builder`. `HookPointDeclaration.sensitive_fields` is validated and stored by `hooks/hook_point_catalog.py`, but no production path applies it before creating `HookInvocationView`. A builder can therefore copy credentials, mutable objects, or undeclared fields into a payload whenever the event schema accepts them.

This contradicts the approved contract in `features/feature-unified-hooks-design.md`: arguments and results must be excluded unless the declaration policy and builder explicitly allow detached JSON fields, and live objects must never be exposed for worker payload construction.

## Impact

The framework cannot be approved as ready for core Hook-point rollout because the declared sensitive-data boundary is advisory rather than enforced. Runtime payload validation detaches and schema-validates the builder output, but it cannot determine whether a field was authorized by the declaration.

## Required correction

Introduce an enforced, detached allowlisted invocation view driven by each declaration's sensitive-field policy, and add negative tests proving undeclared raw arguments, results, credentials, mutable references, exceptions, and tracebacks are unavailable to builders. Preserve original exception identity and traceback behavior.

## Root cause and detection failure

- Root cause: the Catalog stores policy metadata, while the decorator independently constructs its builder view without a policy-enforcement transformation.
- Detection failure: Catalog tests verify only policy storage/shape, and decorator tests use a builder that reads only `phase`; no adversarial test attempts to read or export undeclared argument/result data.

## Resolution

`HookPointDeclaration` now defines explicit phase-local `argument_fields`, `result_fields`, and bounded `error_fields` allowlists. The decorator constructs the builder view only from those fields through bounded JSON detachment; default declarations expose no business data, and `sensitive_fields` remains an additional argument denylist that cannot overlap authorized arguments. Focused adversarial sync/async tests prove undeclared credentials, raw results, exception instances, tracebacks, and mutable business references are unavailable or detached while original exception identity and traceback remain unchanged.

Completion review also found that eager `str(error)` conversion could execute arbitrary exception formatting even when a message was unauthorized. Error metadata now derives `type` from the class name and includes `message` only for one exact-string base-exception argument, without calling exception formatting code. A hostile-`__str__` regression test proves the error Hook still runs and the exact original exception continues to propagate.
