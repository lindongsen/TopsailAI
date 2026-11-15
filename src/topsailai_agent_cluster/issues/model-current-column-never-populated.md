# CURRENT column is always "no" because the adapter never populates it

## Symptom

Every row of the `model` catalog table renders `CURRENT = no`, including the profile the session
is actually using. An operator reads a full column of `no` as "no profile is in use", which is a
false statement about the session.

## Evidence

- `internal/tui/model_catalog.go:94` defines the column.
- `internal/tui/model_catalog.go:111-116` renders `yes` only when `row.Current`, otherwise `no`.
- `internal/tui/model_catalog.go:70` copies `profile.Current` unchanged.
- `internal/protocol/model.go:30` declares `Current bool`.
- `internal/adapter/topsailai/model_catalog.go:100-105` builds `ModelProfile` without setting
  `Current`, so the Go zero value `false` reaches the renderer.

## Root cause

The provider document the adapter reads describes the registry, not the runtime.
`_model_to_record` (`cli/cli_topsailai/models_cli.py:173-200`) emits no current-model field, and
`handle_models_list` (`models_cli.py:287-306`) never resolves the persisted selection. The registry
answers "what can be selected", not "what is in use".

The omission was deliberate and recorded in commit `22f35238`: "Current and Truncated stay empty
because the provider reports neither in this document, and a flag that is always set stops being
read." The defect is the combination: the field was left empty **and** the UI still draws a column
that renders "not obtained" as a definite negative.

## Detection failure

`internal/tui/model_catalog_test.go:164-167` supplies `Current: true` by hand, so the renderer is
covered while the producer is not. `internal/adapter/topsailai/model_catalog_test.go` never mentions
`Current`. `tests/bdd/` never mentions `CURRENT`. A green renderer test certified a value that no
producer emits.

## Impact

The column is misleading rather than merely empty. A `bool` cannot express "not observed", so the
renderer is forced to choose between two definite answers and picks the wrong one.

## Resolution

Option C, chosen by the human: keep the column and make "not observed" an explicit third state.
`Current bool` becomes a closed-vocabulary `CurrentState` with `yes` / `no` / `unknown`; the adapter
states `unknown` because the provider document carries no current-model field; the renderer prints
`unknown` for any value outside the vocabulary. No provider runtime read is added.

See `.task/plan_20261111T182547_model-current-tri-state.md`.

## Reversal: the provider does expose the current model

Recorded on 2026-11-13, after the human asked why CURRENT still carries no information.

The Option C resolution above was correct about the registry document and wrong about the provider.
`models list --json` really does describe only the registry, but the provider exposes the runtime
model through a second, non-interactive surface that the adapter never called.

Producer chain, verified in source:

- `INSTRUCTIONS` registers `llm=get_llm` (`workspace/plugin_instruction/agent.py:430`).
- `get_llm()` returns `agent.runtime.llm_model.model_name` (`agent.py:285-294`).
- `call_instruction` returns that value in `result` (`workspace/control_handlers/instruction.py:105-109`).

Verified live on session `wa-912fd0e49de3`:

```text
topsailai runtime control call_instruction -s wa-912fd0e49de3 \
  -a '{"instruction":"agent.llm","args":[]}' --json
```

returns `"result": "DeepSeek-V4-Flash-Preview"`, which is exactly a registry `name`, so it maps onto
a rendered row without any provider-specific parsing in the cluster.

The defect was therefore not a missing provider capability. It was a cluster-side omission: the
adapter hardcoded `ModelCurrentUnknown` (`internal/adapter/topsailai/model_catalog.go:107`) and never
asked.

## Resolution now in force

Option A, authorized by the human on 2026-11-13: the adapter reads the current model through the
registered `agent.llm` instruction while composing the catalog, and maps the observation onto the
existing tri-state vocabulary.

- An observed name that matches a profile is `yes`; every other profile is `no`.
- An unobserved name, including any read failure, leaves every profile `unknown`. A failed read never
  fails the catalog, because a missing current-model answer must not hide the profiles that exist.
- An observed name absent from the registry yields `no` for every row, because the session is then
  using something other than every published profile. That is an observation, not a gap.

The protocol, the renderer and the column layout are unchanged: the tri-state vocabulary introduced
by Option C is exactly what Option A needed, so the earlier work was not wasted.

The cost is one bounded provider process per catalog read, which is acceptable because the catalog is
read on demand rather than on a timer.

See `.task/plan_20261113T094029_model-guided-selection-and-current-column.md`.
