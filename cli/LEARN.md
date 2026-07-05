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
