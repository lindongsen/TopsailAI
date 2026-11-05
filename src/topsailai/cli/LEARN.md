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

## 2026-09-05: Runtime commands must update every command-discovery surface

### Trigger

A new runtime `/control` command was implemented, but the first review found that the unrecognized-input prompt and the main stream-function documentation still listed only the older runtime commands.

### Action taken

Searched all runtime command help, fallback, and error strings and updated each relevant surface to include `/control`, then re-reviewed the complete file diff.

### Why this prevents recurrence

Treating parsing, dispatch, startup help, fallback help, error guidance, and usage documentation as one command contract prevents a working command from remaining undiscoverable or being incorrectly reported as unavailable in another runtime path.

## FIFO message framing must reject content that collides with its terminator

### Trigger

Runtime `/send` reported success for a multiline message containing a standalone `EOF` line, while the receiving input protocol treated that line as the end marker and discarded the remaining content.

### Action taken

Traced input capture, FIFO writing, and receiver parsing; confirmed that the sender wrote all bytes but the receiver truncated at the in-band marker, then made the CLI reject such messages before opening the pipe because the receiver protocol is outside this workspace.

### Why this prevents recurrence

Validating reserved framing markers before transport prevents silent partial delivery until sender and receiver can adopt a collision-free framing protocol together.

## Process control receipts require instance authority and explicit milestones

### Trigger

The workspace JSON receipt implementation exposed two safety gaps: non-interactive kill authorized a target from a historical log filename and live PID alone, while launch and resume receipts inferred delivery or launcher exit from a return code, background mode, or PID presence.

### Action taken

Required callers to use the verified process generation published only for a live process holding its exact session stdout file, revalidated that identity after opening a pidfd, and failed closed when identity or bound signaling was unavailable. Launch and resume now record submission, observed wait completion, confirmed cancellation, and uncertain effects at their actual boundaries, and receipt states are derived only from those facts.

### Why this prevents recurrence

Binding termination to the current process instance prevents stale logs and PID reuse from authorizing a signal to an unrelated process, while evidence-based receipt states prevent automation from blindly retrying an operation whose side effects may already have occurred or treating PID presence as proof that a launcher exited.

## Non-interactive list commands must share both data and renderer contracts

### Trigger

`topsailai project list_sessions` loaded valid project-session records but displayed blank cells, and its public parser did not propagate `--json` to the command handler.

### Action taken

Reused the interactive project scope's session query and session-table renderer, explicitly forwarded the parsed JSON option, and verified both the installed command entry point and strict JSON parsing with real data.

### Why this prevents recurrence

Treating a reused list as a three-part contract—query, record schema, and renderer/output mode—prevents valid records from being passed to an incompatible table and prevents parser flags from being accepted without changing downstream output.

## Launcher-provided tasks must preserve channel semantics and observable precedence

### Trigger

Adding `--task` initially covered live child delivery, but final review found that dry-run did not represent the explicit option as overriding an inherited `TOPSAILAI_TASK`, and the Unicode regression fixture had been stored as mojibake while still passing an exact round-trip assertion.

### Action taken

Made explicit task precedence visible in dry-run through a redacted placeholder, asserted that neither explicit nor inherited task bodies appear in output, replaced the damaged fixture with real Chinese and emoji text, and made partial task-file writes remove their file before re-raising the original failure.

### Why this prevents recurrence

Testing both semantic precedence and the actual character classes promised by the interface prevents a passing byte-for-byte test from validating corrupted input, while exercising privacy and cleanup at non-execution boundaries keeps dry-run and failed setup behavior consistent with a real launch.

## Temporary sessions have no session ID, so `/meta` must map the display sentinel to the file prefix

### Trigger

Workspace `/meta` rejected every temporary row with `unsupported_row`, even though `topsailai.{pid}.session.meta` files existed and were complete. The user reported that rows without a session ID do have metadata files and must be readable.

### Action taken

Confirmed two independent rejections: the filename check compared against the display sentinel `(temp)` instead of the on-disk prefix `topsailai`, and the reader reused the driver's `metadata_path` guard, which intentionally rejects temporary ids, plus an exact `session_id` equality that a temporary record cannot satisfy because it persists `""`. Added a display-to-file identity mapping, composed the metadata path inside `session_meta` itself, and accepted `""` or `topsailai` as the same absent identity for temporary records only. Verified against the live task directory (2/2 temporary rows now print their metadata) and with unit tests covering both sentinels, both stored identities, both suffixes, mismatch, and absence.

### Why this prevents recurrence

The display layer and the storage layer use different identifiers for the same session, so any path composition or identity check must translate the display sentinel first. Keeping the driver's stricter guard untouched preserves its own safety contract while the read-only metadata path gains exactly the one exception it needs.
