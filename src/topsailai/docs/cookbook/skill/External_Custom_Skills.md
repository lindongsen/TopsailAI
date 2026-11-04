---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
---

# External Custom Skills

How to give the agent a procedure it must follow, by placing one folder where the loader looks.

## Why This Exists

A tool is one function the model may call. A skill is a **procedure**: when to use it, which steps to run,
which files to read, and what each result means. The model cannot invent that reliably from a function
signature, so a skill ships the instructions and the scripts together, and the agent is required to read the
instructions before it executes anything.

| Aspect | Skills | Tools (`TOPSAILAI_PLUGIN_TOOLS`) | Instructions (`TOPSAILAI_PLUGIN_INSTRUCTIONS`) |
|--------|--------|----------------------------------|-----------------------------------------------|
| Who invokes it | The LLM, after reading the skill overview | The LLM, through a tool call | The human, by typing `/name` |
| Unit of extension | A folder with `SKILL.md`, scripts, and references | A Python module with a `TOOLS` dict | A Python module with an `INSTRUCTIONS` dict |
| What it carries | Procedure, domain knowledge, and runnable scripts | One callable action | One human command |
| Discovery | Folder scan, recursive | Direct children of one folder | Direct children of one folder |
| Registry in the prompt | One `## <name>. folder=...` block per skill | The tool-name list | The `/help` listing |
| Enable/disable filter | `TOPSAILAI_DISABLED_SKILLS` | `TOPSAILAI_ENABLED_TOOLS` / `TOPSAILAI_DISABLED_TOOLS` | None |
| Loader | `skill_hub/skill_tool.py:get_skill_markdown()` | `tools/base/common.py:expand_plugin_tools()` | `workspace/plugin_instruction/base/init.py` |

A skill does not replace a tool. The skill decides *when* and *why*; the script it runs does the work.
If the work is a single call the model can already make, a tool is enough and a skill is overhead.

## Where a Skill Can Live

A skill is discovered from four locations. The first one needs no configuration at all, which makes it the
right place for a skill that belongs to this machine rather than to one project.

| Order | Location | Configured by |
|-------|----------|---------------|
| 1 | `{TOPSAILAI_HOME}/skill` | Nothing. `TOPSAILAI_HOME` defaults to `$HOME/.topsailai`. |
| 2 | Every folder in `TOPSAILAI_PLUGIN_SKILLS` | The environment variable |
| 3 | `{TOPSAILAI_PROJECT_WORKSPACE}/.topsailai/skills` | The project workspace variable |
| 4 | `{TOPSAILAI_PWD}/.topsailai/skills` | The process working directory |

The home location is scanned first and needs no variable, so a skill dropped into `{TOPSAILAI_HOME}/skill`
is available to every project that uses the same home:

```bash
export TOPSAILAI_HOME=/tmp/skilldemo/home
mkdir -p /tmp/skilldemo/home/skill
cp -r /TopsailAI/src/topsailai/docs/cookbook/skill/examples/release_check /tmp/skilldemo/home/skill/
uv run python -c "from topsailai.skill_hub.skill_tool import get_skill_markdown; print([l.split('. folder=')[0][3:] for l in get_skill_markdown().splitlines() if l.startswith('## ') and '. folder=' in l])"
```

```text
['release-check']
```

`TOPSAILAI_PLUGIN_SKILLS` is unset in that run, so the skill came from the home folder alone. The same
folder is found one level deeper, which is the layout the installer uses:

```text
A registry (no env var): ['release-check']
B registry (nested under local/): ['release-check']
```

Two consequences follow from the scan order.

- **A skill reachable from several locations is registered several times.** The prompt then carries one
  block per location, while the cache holds a single entry:

  ```text
  home only: blocks=1 cache=1
  home + project: blocks=2 cache=1
  home + project + plugin: blocks=3 cache=1
  ```

  Keep one copy of a skill. Duplicated blocks waste prompt space and make the agent read the same procedure
  twice.

- **The order of `TOPSAILAI_PLUGIN_SKILLS` is not preserved.** The variable is parsed into a set, so the
  scan order of its folders is not the order they were written. Three runs of the same value:

  ```text
  ['/a;/b;/c;/d;/e'] -> ['/d', '/c', '/b', '/e', '/a']
  ['/a;/b;/c;/d;/e'] -> ['/a', '/d', '/e', '/b', '/c']
  ['/a;/b;/c;/d;/e'] -> ['/e', '/a', '/d', '/b', '/c']
  ```

  The exact permutation differs per process, so treat these three lines as evidence that the order is
  unstable rather than as expected output. Both `;` and `,` separate entries. Do not rely on position to
  give one folder precedence over another.

## Quick Start

```bash
export TOPSAILAI_HOME=/tmp/skilldemo/home
export TOPSAILAI_PLUGIN_SKILLS=/TopsailAI/src/topsailai/docs/cookbook/skill/examples
uv run python -c "from topsailai.skill_hub.skill_tool import get_skill_markdown; print([l.split('. folder=')[0][3:] for l in get_skill_markdown().splitlines() if l.startswith('## ') and '. folder=' in l])"
```

```text
['release-check']
```

`TOPSAILAI_HOME` points at an empty folder so the built-in skills under `{TOPSAILAI_HOME}/skill` do not
appear in the output. The agent now sees one skill named `release-check`, and its first move is
`skill_tool-overview_skill` to read the procedure.

## Folder Layout

```text
examples/                        <- point TOPSAILAI_PLUGIN_SKILLS here
└── release_check/               <- one skill; the folder basename is its identity
    ├── SKILL.md                 <- required: front matter plus the procedure
    ├── scripts/
    │   └── check_tree.py        <- the only executable this skill may run
    └── references/
        └── release_policy.md    <- domain knowledge the procedure cites
```

- **The folder basename is the identity.** Two skills with the same basename are a conflict, not two entries.
- **`SKILL.md` or `skill.md`.** Both names are accepted, and `SKILL.md` is checked first.
- **The scan is recursive.** A folder without `SKILL.md` is treated as a container and its sub-folders are
  scanned, up to `TOPSAILAI_SEARCH_SKILLS_MAX_DEPTH` (default `5`).
- **`scripts/` holds source scripts and `bin/` holds compiled binaries.** `call_skill` resolves a bare
  script name against `scripts`, `script`, `bin`, `sbin`, and `tools`, so `check_tree.py` and
  `scripts/check_tree.py` both resolve to the same file.

## The `SKILL.md` Contract

The file has two parts: YAML front matter, and the body the agent reads as the procedure.

| Front-matter key | Required | Effect |
|------------------|----------|--------|
| `name` | Yes | The skill name shown in the prompt. A skill without it is skipped silently. |
| `description` | No | The summary shown in the prompt. When absent, the whole body is used as the summary instead. |
| `flag_overview` | No | `1` forces the full overview into the prompt, `0` suppresses it, and an unset value defers to `TOPSAILAI_LOAD_OVERVIEW_INTO_PROMPT_SKILLS`. |
| `preload_docs` | No | Files or folders appended to the overview. A folder entry loads every `.md` file inside it, recursively, in sorted order. |

The body is not documentation for humans only. It is the instruction set the agent follows, so it must
state the trigger, the exact command to run, and how to interpret each result. A body that only describes
the capability leaves the agent to guess the invocation, which is the failure this mechanism exists to
prevent.

## Example: Read-Only Release Gate

**Scenario.** A release manager is about to publish tag `v1.4.0` and asks the agent whether the tree is
safe to tag. The agent must not improvise git commands, because a wrong `git clean` or `git checkout`
destroys uncommitted work. The skill therefore allows exactly one script, and that script only reads. The
blocking conditions live in a reference document so the policy can be reviewed without reading code.

`docs/cookbook/skill/examples/release_check/SKILL.md`:

````markdown
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
````

`docs/cookbook/skill/examples/release_check/scripts/check_tree.py`:

```python
#!/usr/bin/env python3
"""Read-only release gate for one git repository.

Scenario: a release manager is about to publish a tag and asks the agent whether
the tree is safe to tag. The agent must not improvise git commands, because a
wrong `git clean` or `git checkout` destroys uncommitted work. This script is the
only thing the skill allows to run, and it only reads.
"""

import subprocess
import sys
from pathlib import Path

MAX_FILES = 20
GIT_TIMEOUT = 30


def _git(repo: str, *args: str) -> str:
    """Run one read-only git command and return its standard output.

    Args:
        repo: Absolute path of the repository working tree.
        args: The git subcommand and its arguments.

    Returns:
        The command standard output.

    Raises:
        RuntimeError: When git exits non-zero.
    """
    result = subprocess.run(
        ["git", "-C", repo, *args],
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or f"git {args[0]} failed"
        raise RuntimeError(message)
    return result.stdout


def _lines(text: str) -> list[str]:
    """Split command output into non-empty stripped lines.

    Args:
        text: Raw command output.

    Returns:
        The non-empty lines.
    """
    return [line for line in text.splitlines() if line.strip()]


def _upstream(repo: str) -> str:
    """Return the configured upstream reference of the current branch.

    Args:
        repo: Absolute path of the repository working tree.

    Returns:
        The upstream reference such as `origin/main`, or an empty string when
        the branch has no upstream configured.
    """
    result = subprocess.run(
        ["git", "-C", repo, "rev-parse", "--abbrev-ref", "@{upstream}"],
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _report(repo: str, tag: str) -> tuple[list[str], list[str]]:
    """Collect the blocking and informational facts of one repository.

    Args:
        repo: Absolute path of the repository working tree.
        tag: The tag name the release manager intends to publish.

    Returns:
        A tuple of (blocking lines, informational lines).
    """
    branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
    head = _git(repo, "rev-parse", "--short", "HEAD").strip()

    dirty = _lines(_git(repo, "status", "--porcelain", "--untracked-files=normal"))
    tracked_dirty = [line for line in dirty if not line.startswith("??")]
    untracked = [line for line in dirty if line.startswith("??")]

    existing_tag = _lines(_git(repo, "tag", "--list", tag))

    upstream = _upstream(repo)
    ahead = _lines(_git(repo, "log", "--oneline", f"{upstream}..HEAD")) if upstream else []

    blocking = []
    if tracked_dirty:
        blocking.append(f"tracked files modified: {len(tracked_dirty)}")
        blocking.extend(f"  {line}" for line in tracked_dirty[:MAX_FILES])
        if len(tracked_dirty) > MAX_FILES:
            blocking.append(f"  (+{len(tracked_dirty) - MAX_FILES} more)")
    if existing_tag:
        blocking.append(f"tag already exists: {tag}")
    if not upstream:
        blocking.append("branch has no upstream, so pushed state cannot be verified")
    elif ahead:
        blocking.append(f"commits not pushed: {len(ahead)}")
        blocking.extend(f"  {line}" for line in ahead[:MAX_FILES])

    info = [
        f"branch: {branch}",
        f"head: {head}",
        f"upstream: {upstream or '-'}",
        f"untracked files: {len(untracked)}",
    ]
    info.extend(f"  {line}" for line in untracked[:MAX_FILES])
    if len(untracked) > MAX_FILES:
        info.append(f"  (+{len(untracked) - MAX_FILES} more)")

    return blocking, info


def main(argv: list[str]) -> int:
    """Print the release gate report.

    Args:
        argv: Command-line arguments: <repo> <tag>.

    Returns:
        0 when the tree is ready, 1 when it is blocked, 2 on usage error.
    """
    if len(argv) != 2:
        print("usage: check_tree.py <repo> <tag>", file=sys.stderr)
        return 2

    repo, tag = argv
    if not Path(repo).is_dir():
        print(f"error: not a directory: {repo}", file=sys.stderr)
        return 2

    try:
        blocking, info = _report(repo, tag)
    except (RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"release gate for tag {tag}")
    for line in info:
        print(line)

    if blocking:
        print("verdict: BLOCKED")
        for line in blocking:
            print(line)
        return 1

    print("verdict: READY")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

`docs/cookbook/skill/examples/release_check/references/release_policy.md`:

```markdown
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
```

## Running the Skill

The skill is invoked through the `call_skill` tool, which returns `(return_code, stdout, stderr)`.

The demo repository is built with fixed commit dates, so the short hashes below are reproducible on any
machine:

```bash
export GIT_AUTHOR_DATE="2026-01-01T00:00:00+0000"
export GIT_COMMITTER_DATE="2026-01-01T00:00:00+0000"
git init -q --bare -b main /tmp/skilldemo/demo/origin.git
git init -q -b main /tmp/skilldemo/demo/repo
cd /tmp/skilldemo/demo/repo
git config user.email "release@example.com"
git config user.name "Release Bot"
git remote add origin /tmp/skilldemo/demo/origin.git
printf 'version = "1.4.0"\n' > version.txt
git add version.txt
git commit -q -m "prepare 1.4.0"
git push -q -u origin main
```

A clean tree with a pushed branch:

```python
call_skill(
    skill_folder="/TopsailAI/src/topsailai/docs/cookbook/skill/examples/release_check",
    script_path="scripts/check_tree.py",
    script_parameters=["/tmp/skilldemo/demo/repo", "v1.4.0"],
)
```

```text
(0, 'release gate for tag v1.4.0\nbranch: main\nhead: 82ce2d7\nupstream: origin/main\nuntracked files: 0\nverdict: READY', '')
```

The same repository after a tag was created, one commit was made, and one file was left untracked. The block
starts with `cd` on purpose: `git tag` and `git commit` act on the repository of the current directory, so
running these lines from a project checkout would tag and commit that project instead of the demo.

```bash
cd /tmp/skilldemo/demo/repo
export GIT_AUTHOR_DATE="2026-01-02T00:00:00+0000"
export GIT_COMMITTER_DATE="2026-01-02T00:00:00+0000"
git tag v1.4.0
printf 'version = "1.4.1"\n' > version.txt
git add version.txt
git commit -q -m "prepare 1.4.1"
printf 'scratch\n' > notes.tmp
```

```text
(1, 'release gate for tag v1.4.0\nbranch: main\nhead: cf3c12b\nupstream: origin/main\nuntracked files: 1\n  ?? notes.tmp\nverdict: BLOCKED\ntag already exists: v1.4.0\ncommits not pushed: 1\n  cf3c12b prepare 1.4.1', '')
```

The exit code carries the verdict, so the agent does not have to parse prose to decide. `0` means the tree
may be tagged, `1` means it may not, and `2` means the gate could not run at all.

A bare script name resolves to the same file, so the agent does not have to know the sub-folder:

```text
(1, 'release gate for tag v1.4.0\nbranch: main\nhead: cf3c12b\nupstream: origin/main\nuntracked files: 1\n  ?? notes.tmp\nverdict: BLOCKED\ntag already exists: v1.4.0\ncommits not pushed: 1\n  cf3c12b prepare 1.4.1', '')
```

## What the Agent Sees

`overview_skill` returns the body of `SKILL.md` without its front matter, the folder inventory, and every
preloaded document. This is the output the agent must read before it runs anything:

````text

>>> [SKILL_OVERVIEW_START:/TopsailAI/src/topsailai/docs/cookbook/skill/examples/release_check]

<file path="SKILL.md">

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

</file>

## folder content
- SKILL.md
- scripts/check_tree.py
- references/release_policy.md

<file path="references/release_policy.md">
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

</file>

<<< [SKILL_OVERVIEW_END:/TopsailAI/src/topsailai/docs/cookbook/skill/examples/release_check]

````

The `## folder content` section is generated from the real folder, so a file the agent may need is visible
even when the body does not mention it. The `references/release_policy.md` block appears because
`preload_docs` lists it, and because the skill was already discovered when the overview was rendered.

That last condition is a real limitation. `overview_skill` reads `preload_docs` from the skill cache, so a
folder that was never discovered renders the body and the inventory but no preloaded document:

```text
cache: []
has preload block: False
```

```text
cache: ['/TopsailAI/src/topsailai/docs/cookbook/skill/examples/release_check']
has preload block: True
```

In a normal session the skill is discovered at startup, so the preloaded documents are present. The empty
case only appears when a folder is passed to `overview_skill` without ever being registered.

## The Four Skill Tools

| Tool | Purpose | Notable constraint |
|------|---------|--------------------|
| `skill_tool-overview_skill` | Return the full procedure, folder inventory, and preloaded documents | Requires the folder to contain `SKILL.md` |
| `skill_tool-call_skill` | Run one script inside the skill folder | The script must exist inside the folder and carry the executable bit |
| `skill_tool-read_skill_file` | Read one text file inside the skill folder | The skill must already be loaded into the registry |
| `skill_tool-load_skill` | Add a folder to `TOPSAILAI_PLUGIN_SKILLS` and register it | Fails when the skill is disabled or its basename conflicts |

`call_skill` is the only tool that executes anything, and it refuses every path that resolves outside the
skill folder. That boundary is what makes a third-party skill safe to install: the skill cannot reach the
rest of the filesystem through the tool, only through whatever the script itself is allowed to do.

## Rejected Inputs

A script path that escapes the folder:

```text
SkillToolError: A skill can only run scripts that exist inside its own folder. The requested script '../outside.py' was not found inside '/TopsailAI/src/topsailai/docs/cookbook/skill/examples/release_check' or is outside the skill folder.
```

A script that does not exist:

```text
SkillToolError: A skill can only run scripts that exist inside its own folder. The requested script 'scripts/missing.py' was not found inside '/TopsailAI/src/topsailai/docs/cookbook/skill/examples/release_check' or is outside the skill folder.
```

A relative skill folder:

```text
SkillToolError: Skill folder does not exist or is not a directory. Provided: 'docs/cookbook/skill/examples/release_check'. Check the folder path and ensure the skill is loaded.
```

A script without the executable bit:

```text
SkillToolError: Script '/tmp/skilldemo/noexec/scripts/run.py' exists but is not executable. Run 'chmod +x /tmp/skilldemo/noexec/scripts/run.py' or invoke it with an interpreter such as 'python /tmp/skilldemo/noexec/scripts/run.py'.
```

Reading outside the folder, by traversal and by absolute path:

```text
SkillToolError: file_name must be inside the skill folder, got '../SKILL.md'. Use a relative path such as 'scripts/run.sh' or 'README.md'.
```

```text
SkillToolError: file_name must be inside the skill folder, got '/etc/passwd'. Use a relative path such as 'scripts/run.sh' or 'README.md'.
```

A script that runs but rejects its own arguments still returns a tuple rather than raising, so the agent
can report the usage error instead of crashing:

```text
(2, '', 'usage: check_tree.py <repo> <tag>')
```

```text
(2, '', 'error: not a directory: /tmp/does-not-exist')
```

## Discovery, Disable, and Overview

| Input | Observed result |
|-------|-----------------|
| Valid `SKILL.md` with `name` | Registered as `good-skill` |
| Front matter without `name` | Skipped, no error |
| Invalid YAML front matter | Skipped, with `failed to parse SKILL.md front matter` printed |
| Folder without `SKILL.md` | Skipped, sub-folders scanned instead |
| Lowercase `skill.md` | Registered as `lower-skill` |
| `TOPSAILAI_DISABLED_SKILLS=good-skill` | Not registered |
| `TOPSAILAI_DISABLED_SKILLS=good` | Not registered, matched by folder basename |
| `TOPSAILAI_DISABLED_SKILLS=*` | Not registered |
| Nested skill at depth 4 | Registered at the default depth `5` |
| Same nested skill with `TOPSAILAI_SEARCH_SKILLS_MAX_DEPTH=1` | Not registered |
| Duplicate basename with different `SKILL.md` | Second folder rejected with `Conflicting skill folder name detected` |
| Duplicate basename with identical `SKILL.md` | Accepted, the cached entry is reused |

Disabling a skill removes it from the prompt, but it does not remove the folder from the filesystem, so a
direct `call_skill` on that folder still runs:

```text
(1, 'release gate for tag v1.4.0\nbranch: main\nhead: cf3c12b\nupstream: origin/main\nuntracked files: 1\n  ?? notes.tmp\nverdict: BLOCKED\ntag already exists: v1.4.0\ncommits not pushed: 1\n  cf3c12b prepare 1.4.1', '')
```

`load_skill` on the same disabled folder fails, because registration is what it performs:

```text
SkillToolError: load skill failed: /TopsailAI/src/topsailai/docs/cookbook/skill/examples/release_check (no valid SKILL.md, skill disabled, or duplicate basename already loaded)
```

Overview loading is controlled by `TOPSAILAI_LOAD_OVERVIEW_INTO_PROMPT_SKILLS`, which matches the folder
path or its basename, not the skill name:

| Value | Overview rendered |
|-------|-------------------|
| unset | No |
| `release_check` | Yes |
| `release-check` | No, the skill name is not the folder name |
| `./release_check` | Yes |
| `release_check/` | Yes |
| full folder path | Yes |
| full folder path with a trailing slash | Yes |
| `*` | Yes |
| an unrelated name | No |

`flag_overview` in the front matter wins over the environment variable in both directions. `preload_docs`
never renders on its own, because it is part of the overview:

| Front matter | `TOPSAILAI_LOAD_OVERVIEW_INTO_PROMPT_SKILLS` | Overview rendered | `preload_docs` rendered |
|--------------|---------------------------------------------|-------------------|-------------------------|
| unset | unset | No | No |
| unset | `*` | Yes | Yes |
| `flag_overview: 1` | unset | Yes | Yes |
| `flag_overview: 0` | `*` | No | No |
| no `description` | unset | Yes, as the description | Yes |

Two couplings are worth remembering.

- **`preload_docs` is rendered as part of the overview**, so a skill that preloads a reference document
  shows nothing extra until the overview is enabled.
- **A skill without `description` always shows its overview**, because the body is used as the summary
  and the loader then skips the separate overview append. That is why the last row renders the overview
  without the environment variable.

## Installing and Removing Skills

`skill_hub/skill_repo.py` manages the home location, and the `/list`, `/install`, and `/uninstall`
instructions expose it to a human. An install copies the folder into `{TOPSAILAI_HOME}/skill/local/<basename>`:

```text
install_skill -> /tmp/skilldemo/home/skill/local/release_check
list_skills() after install: ['local/release_check']
install again -> /tmp/skilldemo/home/skill/local/release_check
uninstall -> True
list_skills() after uninstall: []
uninstall missing -> False
```

- **Installing the same folder twice is a no-op.** The existing destination is returned unchanged.
- **`uninstall_skill` takes the relative path**, such as `local/release_check`, and returns `False` when
  the folder is already gone.
- **`list_skills()` scans only the home location**, so a skill installed through `TOPSAILAI_PLUGIN_SKILLS`
  does not appear in that listing.

## Requirements and Limitations

| Requirement | Behavior |
|-------------|----------|
| `SKILL.md` present | Required. A folder without it is scanned for sub-folders instead. |
| `name` in front matter | Required. Without it the skill is skipped without a message. |
| Front matter parses as YAML | Required. A plain scalar containing `: ` becomes a nested mapping and the skill is skipped. |
| Absolute skill folder | Required by `call_skill`. A relative path raises `SkillToolError`. |
| Script inside the folder | Required. `..` traversal and outside absolute paths are rejected. |
| Executable bit on the script | Required. A non-executable file raises `SkillToolError` before any process starts. |
| Unique folder basename | Required. A conflicting basename with different content is rejected. |
| `TOPSAILAI_SEARCH_SKILLS_MAX_DEPTH` | Default `5`. A deeper skill is not discovered. |
| `TOPSAILAI_DISABLED_SKILLS` | Blocks discovery and `load_skill`, but not a direct `call_skill`. |
| `preload_docs` | Rendered only when the overview is enabled and the skill is already discovered. |
| `TOPSAILAI_CALL_SKILL_TIMEOUT_MAP` | Matched against the folder path, not the skill name. `release_check=900` matches, `release-check=900` does not. |
| Timeout argument | `call_skill` uses the larger of its `timeout` argument and the mapped value, so the map is a floor, not an override. |
| `output_file` | Must be an absolute path, and an existing file outside a temporary folder is never overwritten. |
| `read_skill_file` | Requires the skill to be loaded into the registry first. |
| Duplicate location | A skill reachable from several locations is registered once per location. |

The timeout map is worth one concrete example, because the key is the folder and not the skill:

```text
timeout default without map: 600
timeout matched by folder basename: 900
timeout not matched by skill name: 600
timeout matched by full path: 1200
timeout map default key: 300
```

An invalid value is rejected rather than silently ignored:

```text
SkillToolError: Invalid timeout value for 'release_check' in TOPSAILAI_CALL_SKILL_TIMEOUT_MAP: 'abc' is not an integer. Use a positive integer in seconds, e.g. 'ai-community=86400'.
```

## Load Timing

`topsailai/tools/skill_tool.py` builds the registry prompt once, at import time, through `reload()`:

```text
FLAG_TOOL_ENABLED at import: False
registry in PROMPT at import: False
after adding folder, PROMPT contains late-skill: False
after reload(), PROMPT contains late-skill: True
FLAG_TOOL_ENABLED after reload: True
```

Consequences:

- `TOPSAILAI_PLUGIN_SKILLS` must be set **before** the process starts.
- Adding a skill folder later has no effect on the prompt until `reload()` runs.
- `FLAG_TOOL_ENABLED` is `False` when no skill is discovered, which hides the whole skill tool module from
  the agent. A project with no skills therefore pays nothing for this mechanism.
- `/load` and `/unload` call `load_skill` and `unload_skill`, which update the environment variable and the
  cache and then reload the tool prompt, so an interactive session can pick up a new skill without a restart.

## Verifying Without an Agent Session

`topsailai_simulate_agent_execute` runs the execution phase headlessly, so a skill can be exercised without
a live LLM:

```bash
export TOPSAILAI_HOME=/tmp/skilldemo/home
export TOPSAILAI_PLUGIN_SKILLS=/TopsailAI/src/topsailai/docs/cookbook/skill/examples
uv run python cli/topsailai_simulate_agent_execute.py \
    --show-tools --only-tools skill_tool \
    --file /tmp/skilldemo/sim3/resp.txt
```

The response file uses the plain `topsailai.<step>` format:

```text
topsailai.thought
The release manager wants to tag v1.4.0. I will run the release gate skill instead of improvising git commands.
topsailai.action
{"tool_call": "skill_tool-call_skill", "tool_args": {"skill_folder": "/TopsailAI/src/topsailai/docs/cookbook/skill/examples/release_check", "script_path": "scripts/check_tree.py", "script_parameters": "[\"/tmp/skilldemo/demo/repo\", \"v1.4.0\"]"}}
topsailai.final_answer
The gate returned BLOCKED: the tag v1.4.0 already exists and one commit is not pushed.
```

```text
[available_tools] [4] ['skill_tool-call_skill', 'skill_tool-load_skill', 'skill_tool-overview_skill', 'skill_tool-read_skill_file']
[0] thought
The release manager wants to tag v1.4.0. I will run the release gate skill instead of improvising git commands.
The gate returned BLOCKED: the tag v1.4.0 already exists and one commit is not pushed.

[1] action
{"tool_call": "skill_tool-call_skill", "tool_args": {"skill_folder": "/TopsailAI/src/topsailai/docs/cookbook/skill/examples/release_check", "script_path": "scripts/check_tree.py", "script_parameters": "[\"/tmp/skilldemo/demo/repo\", \"v1.4.0\"]"}}
-> observation: {'step_name': 'observation', 'raw_text': (1, 'release gate for tag v1.4.0\nbranch: main\nhead: cf3c12b\nupstream: origin/main\nuntracked files: 1\n  ?? notes.tmp\nverdict: BLOCKED\ntag already exists: v1.4.0\ncommits not pushed: 1\n  cf3c12b prepare 1.4.1', '')}

Final answer:
The gate returned BLOCKED: the tag v1.4.0 already exists and one commit is not pushed.
```

The observation is the raw `call_skill` tuple, so the exit code and both streams reach the agent unchanged.
Note that a `final_answer` placed directly after an `action` is folded into the preceding `thought` by the
`action_with_final_answer` mistake rule, which is why the transcript shows both sentences under `[0] thought`.
That is expected framework behavior, not a skill defect.

## Related Documents

- [Environment Variables](../../Environment_Variables.md) — `TOPSAILAI_PLUGIN_SKILLS`, `TOPSAILAI_DISABLED_SKILLS`, `TOPSAILAI_SEARCH_SKILLS_MAX_DEPTH`, `TOPSAILAI_LOAD_OVERVIEW_INTO_PROMPT_SKILLS`, `TOPSAILAI_CALL_SKILL_TIMEOUT_MAP`, `TOPSAILAI_SESSION_LOCK_ON_SKILLS`, `TOPSAILAI_SESSION_REFRESH_ON_SKILLS`, `TOPSAILAI_HOOK_MODULE_SKILLS`
- [External Custom Tools](../tool/External_Custom_Tools.md) — the same folder mechanism for LLM-callable functions
- [External Custom Instructions](../instruction/External_Custom_Instructions.md) — the same folder mechanism for `/` commands
- [Plugin Mechanisms](../../../features/feature-plugin-mechanisms.md) — how plugins, hooks, and events differ
