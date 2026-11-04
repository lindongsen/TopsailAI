---
name: release-check
description: |
  Decide whether one git repository is safe to tag for release.

  Trigger this skill when the user asks "can I tag this", "is the tree clean
  enough to release", "check the release gate", or when a release step must be
  approved before a tag is published.

  The skill runs one read-only script and returns a READY or BLOCKED verdict.
  It never commits, cleans, checks out, or pushes.
preload_docs:
  - references/release_policy.md
---

# Release Check

You are the release gate for one repository. Your job is to answer a single
question: **may this tree be tagged right now?**

## Trigger

Use this skill when the user wants to publish a tag, cut a release, or asks
whether the working tree is in a releasable state.

Do not use it for ordinary commit review, and do not use it to fix the tree.

## Execution

1. Read `references/release_policy.md` to know which conditions block a release.
2. Run the gate script with the repository path and the intended tag:

   ```text
   call_skill(
       skill_folder="<this skill folder>",
       script_path="scripts/check_tree.py",
       script_parameters=["<absolute repo path>", "<tag>"],
   )
   ```

3. Read the exit code and the printed verdict.

## Result handling

| Exit code | Verdict line | What you report |
|---|---|---|
| `0` | `verdict: READY` | The tree may be tagged. State the branch, head, and untracked count. |
| `1` | `verdict: BLOCKED` | List every blocking line verbatim. Do not tag. |
| `2` | `error: ...` | The gate could not run. Report the error and stop. |

## Constraints

- Never run `git commit`, `git clean`, `git checkout`, `git reset`, or
  `git push` to make the gate pass. The gate reports; the human decides.
- Never edit files to silence a blocking line.
- Report the verdict exactly as printed. Do not upgrade `BLOCKED` to `READY`
  because the blocking items look harmless.
