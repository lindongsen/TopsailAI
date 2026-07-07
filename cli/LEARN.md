# Lessons Learned

## 2026-07-05: Configuration edits must preserve existing values and land at the exact path

### Root cause

1. **Did not read the file first**
   - When asked to modify `.topsailai/settings.yaml`, I did not read it before editing.
   - I assumed the structure and ended up writing changes from scratch, which deleted the existing top-level `ai_agent_driver` default.

2. **Did not place the value at the exact path the user specified**
   - The user said the driver should go in `environment.topsailai`.
   - I first put it at the top level, then moved it to `environment._default`, and only after repeated correction put it in `environment.topsailai`.
   - Each move was an assumption rather than following the explicit instruction.

3. **Did not verify after writing**
   - After each write I declared success without re-reading the file.
   - This allowed the deleted default and wrong nesting to go unnoticed until the user checked `git diff`.

### Why the initial request was not fulfilled

- I treated a config change as trivial and skipped the read step.
- I relied on the final summary in the conversation instead of the actual file on disk.

### Why the fixes kept being wrong

- I was reacting to the last message instead of the original requirement.
- I did not confirm the YAML path literally; I interpreted "environment configuration" as `_default` because that is the common pattern.
- I did not check `git diff` to see the full effect of my edits.

### What to do next time

1. **Always read first**: use `read_file` on the target file before any edit.
2. **Write the exact path**: if the user says `environment.topsailai`, write exactly `environment.topsailai`, not `_default` and not the top level.
3. **Preserve existing values**: add or update only the requested keys; never overwrite the whole file unless explicitly asked.
4. **Verify immediately**: after writing, read the file and run `git diff` to confirm only the intended changes were made.
5. **Report precisely**: state exactly which keys were added, updated, or left untouched, and at which paths.

## 2026-07-07: Patching a function and then calling it for real data causes infinite loops

### Root cause

1. **Patched the loader while trying to use its real output**
   - `test_bare_cd_from_project_with_real_yaml` decorated the method with `@patch("cli_topsailai.yaml_commands.load_yaml_commands")`.
   - Inside the test it called `load_yaml_commands()` expecting the real YAML command list.
   - Because the patch was active, `load_yaml_commands` was a `MagicMock`; calling it returned another `MagicMock`, not the real commands.

2. **MagicMock silently broke downstream logic**
   - `cli_state.yaml_commands` became a `MagicMock`.
   - Iterating over a `MagicMock` yields nothing, so the command matcher found no `/cd` instruction.
   - `prompt_selection` fell into its `while True` input loop: every `"cd"` input printed `Unknown command: 'cd'` and requested more input, which kept returning `"cd"` forever.

3. **No protective guard during execution**
   - The test was run without a timeout or resource cap.
   - The infinite loop consumed memory/CPU until the system froze.

### Why the initial request was not fulfilled

- The test claimed to use "real YAML" but still patched the real loader, so the YAML commands were never actually loaded.
- I trusted the test intent ("real yaml") without inspecting whether the patch made that impossible.

### Why it was not caught earlier

- The test file had other passing tests, so the bad test was assumed to be safe.
- No timeout was used when running the specific test, so the hang was not bounded.
- `MagicMock` returns `MagicMock` for any attribute access or call, making failures non-obvious until runtime behavior diverges.

### What to do next time

1. **Do not patch the function you need real data from**: if a test needs real YAML commands, import and call the real loader without a patch, or explicitly stop/unpatch first.
2. **Inspect patched return values**: when patching is necessary, assert the mock returns the expected shape/type before using it in stateful objects.
3. **Run loop-prone tests with a timeout**: use `timeout` (or the test framework's timeout) when executing tests that involve input loops, event loops, or `while True` code paths.
4. **Add circuit-breakers in interactive loops**: production input loops should have a maximum iteration count or an explicit escape when the same unrecognized command repeats.
5. **Verify the fix with the exact failing test name**: after editing, run the specific test first, then the surrounding class, then the full file.

## 2026-07-07: Sort direction and limit interact when fetching paginated data

### Trigger
The user asked to display the project scope list oldest-first (older entries at the top, newer at the bottom).

### What I did wrong first
I changed the `ai_list_sessions.py` argument from `--sort desc` to `--sort asc`, thinking that would simply reverse the display order.

### Correct fix
Keep `--sort desc` so the database returns the newest N entries, then call `sessions.reverse()` after parsing the JSON so the UI renders them oldest-first.

### Why the first approach was wrong
When a `--limit N` is applied, the sort direction determines which N records are returned, not just their display order. Using `--sort asc` would fetch the oldest N sessions and silently discard newer ones; `--sort desc` fetches the newest N, and reversing afterward preserves all recent data while still showing the oldest entry at the top.

### What to do next time
- Distinguish between "fetch order" and "display order" when a limit is involved.
- If the requirement is oldest-first UI but only the latest N records matter, fetch newest-first and reverse locally.
- Verify ordering assumptions with tests that include both timestamps and row numbers.
