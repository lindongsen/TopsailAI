# Release Policy

Which conditions block a release tag, and why.

## Blocking conditions

| Condition | Why it blocks |
|---|---|
| Tracked files modified but not committed | The tag would not describe the code that was tested. |
| The tag name already exists | Re-tagging silently moves a published release. |
| Local commits not pushed to the upstream branch | The tag would point at a commit no other machine can fetch. |

## Non-blocking conditions

| Condition | Why it is only reported |
|---|---|
| Untracked files | They are not part of the tagged tree, so they cannot change the release content. They are listed so the human can spot a forgotten new file. |

## Verdict rules

- Any blocking condition present: `verdict: BLOCKED`, exit code `1`.
- No blocking condition: `verdict: READY`, exit code `0`.
- The gate cannot inspect the repository: `error: ...`, exit code `2`.

## Why the gate is read-only

A release gate that repairs the tree is not a gate. If the script could commit or
clean, a blocked release would become a silent rewrite of the working tree, and
the human would lose the chance to decide what happens to uncommitted work.
