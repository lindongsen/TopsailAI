---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
author: DawsonLin
status: resolved
---

# Issue: BDD entrypoint gate-order assertion is stale after the tee refactor

## Symptom

`tests/unit/test_bdd_entrypoints.py::test_packaged_gate_is_explicit` fails on every
run, including a pristine checkout at `e0db1376`:

```text
assert 1237 < 937
```

The assertion is:

```python
assert output.index("dev-tools deb-build-cython-py3") < output.index('-m "packaged"')
```

It expects the deb build to be printed before the packaged pytest selection in the
`make -n test-bdd-packaged` dry-run output.

## Root cause

The test was written against the pre-refactor recipe. Commit `655d5474`
(2026-11-05) added the test together with a recipe whose lines were emitted in
source order, so the sub-make expansion of `build-deb` appeared before the pytest
line.

Commit `815b9aac` (2026-11-15) rewrote every test target to tee its output into a
timestamped log. The recipe body is now a single shell block:

```make
test-bdd-packaged: test-log-init
	@LOG_FILE="$(LOG_DIR)/test-bdd-packaged_$(LOG_TS).log"; \
	{ \
		$(MAKE) -C "$(REPOSITORY_ROOT)" build-deb && \
		... -m "packaged" tests/bdd ; \
	} 2>&1 | tee "$$LOG_FILE"; \
```

`make -n` prints the whole block as one command string, so the literal
`-m "packaged"` inside the block appears at offset 937, while the sub-make
expansion of `build-deb` (which `make -n` still expands recursively) is appended
afterwards at offset 1237. The ordering the test asserts no longer exists in the
dry-run text, although the real execution order is still correct: `build-deb`
runs first because of the `&&` chain.

## Impact

The failure is a stale assertion, not a broken gate. The packaged acceptance gate
still builds the deb before running the packaged scenarios. The test cannot
distinguish "the recipe runs the build first" from "the dry-run text prints the
build first", and the tee refactor changed only the latter.

## Reproduction

```text
PYTHONPATH=/TopsailAI/src:/TopsailAI/src/topsailai python -m pytest \
  tests/unit/test_bdd_entrypoints.py -q --tb=line --color=no
```

Result on the current tree and on a pristine worktree at `e0db1376`: 1 failed,
3 passed. The failure is deterministic across three consecutive runs.

## Suggested fix

Assert the execution order structurally instead of by string offset. Either
inspect the `&&` chain inside the recipe block, or run the target with a
`$(MAKE)` stub that records invocation order. A string-offset assertion on
`make -n` output is fragile because any recipe that wraps its body in a shell
block changes the printed order without changing the executed order.

## Analysis and closure (2026-11-17)

### The reported failure was real, and it is already fixed

The issue was filed at 10:59 on 2026-11-17 against `e0db1376`. Commit `6926c081`
("test: assert packaged gate order structurally instead of by string offset",
14:35 the same day) replaced the stale assertion, so the issue text describes a
state that no longer exists.

Current assertion in `tests/unit/test_bdd_entrypoints.py::test_packaged_gate_is_explicit`:

```python
build_at = output.index("build-deb")
packaged_at = output.index('-m "packaged"')
assert build_at < packaged_at
assert "&&" in output[build_at:packaged_at]
```

### Verification

`PYTHONPATH=/TopsailAI/src:/TopsailAI/src/topsailai python -m pytest
tests/unit/test_bdd_entrypoints.py -q --tb=line --color=no` -> **4 passed** in 36.69s.

Negative control on the same dry-run output, comparing the old and new assertion
verbatim:

| Assertion | Offsets | Result |
|---|---|---|
| old `dev-tools deb-build-cython-py3` < `-m "packaged"` | 1237 vs 937 | **FAIL** (reproduces the reported `assert 1237 < 937`) |
| new `build-deb` < `-m "packaged"` | 394 vs 937 | **PASS** |

The old offsets match the numbers in the issue exactly, which confirms the
diagnosis: `make -n` prints the tee block as one command string, so the literal
`-m "packaged"` appears at 937 while the recursive `$(MAKE) build-deb` expansion
is appended afterwards at 1237. The executed order was never wrong; only the
printed order changed.

The recipe at `e0db1376` is byte-identical to the current one, so the failure was
deterministic there too. Reproducing the full test inside a worktree was not
possible because that worktree's virtualenv lacks `pytest_bdd`
(`ImportError: No module named 'pytest_bdd'`), so the comparison was done on the
dry-run text directly instead of claiming an executed test result.

### Residual gap found during review (not covered by the fix)

The replacement assertion is structural but still weaker than it looks. It checks
that *some* `&&` appears between the two literals, not that `build-deb` itself is
chained. Mutation testing on the real dry-run output:

| Mutation | Current assertion |
|---|---|
| `build-deb` removed | FAIL (caught) |
| `build-deb` moved after the pytest step | FAIL (caught) |
| `build-deb` followed by `;` instead of `&&` | **PASS (missed)** |

The third case is the one that matters operationally: with `;` the deb build can
fail and the packaged scenarios still run, which is exactly the "silently
unverified acceptance" failure this gate exists to prevent. The `&&` that
satisfies the current check belongs to the following `mkdir ... && cd ...` pair,
not to the build step.

A stricter form that closes the gap, verified to pass on the real recipe and to
fail on the `;` mutation:

```python
tail = output[build_at + len("build-deb"):packaged_at]
assert re.match(r"\s*&&", tail)
```

This stricter form has since been applied (commit "test: require the deb build to
be chained before packaged scenarios"), together with `import re`. Mutation
testing on the real dry-run output confirms the difference:

| Mutation | Previous assertion | Applied assertion |
|---|---|---|
| `build-deb` removed | FAIL (caught) | FAIL (caught) |
| `build-deb` moved after the pytest step | FAIL (caught) | FAIL (caught) |
| `build-deb` followed by `;` instead of `&&` | **PASS (missed)** | **FAIL (caught)** |

`tests/unit/test_bdd_entrypoints.py` -> 4 passed after the change.
