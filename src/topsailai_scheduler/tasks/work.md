# Daily work housekeeping

Two jobs, in this order. Finish the first before starting the second, because
the second produces files that the next day's commit will pick up.

## Job 1: commit the day's work

The repository is `/work`, branch `main`, remote `git@github.com:lindongsen/work.git`.

### Never commit a binary

A binary is any file whose content is machine code rather than text: compiled
executables, shared libraries, object files, and archives of them. Check with
`file --mime-type`; anything reporting `application/x-executable`,
`application/x-sharedlib`, `application/x-pie-executable`, or
`application/x-object` is a binary.

Binary files must be ignored, not committed. If a binary shows up as untracked,
add its path or pattern to `.gitignore` instead of staging it. If a binary is
already tracked, do not remove it in this task: report it and leave it alone,
because some of them have no source in the repository and removing them would
lose the only copy.

### Steps

1. Run `git status --short` and read every line. Note which entries are
   untracked, modified, and deleted.
2. Run `git diff` and `git diff --cached` and read the actual changes. Do not
   commit anything you have not read.
3. Classify each untracked path. A binary goes to `.gitignore`. A generated
   artifact (`.pyc`, `__pycache__`, `.venv`, `node_modules`, a build output
   folder, a log, a cache) goes to `.gitignore`. A real source, document, or
   configuration file is committed. Be careful with a folder named `build`: it
   often holds the build configuration itself (`build.yaml`, templates,
   packaging scripts), so ignore only its generated subfolder, such as
   `build/output/`, never the whole folder.
4. Stage the text files only, by explicit path. Never use `git add -A` or
   `git add .`, because they sweep in whatever else happens to be there.
5. Before committing, run `git diff --cached --stat` and confirm no binary is
   staged. If one is, unstage it by path and add it to `.gitignore` instead.
6. Commit with a message in the form `<type>: <description>`, imperative mood,
   no trailing punctuation. Types: `feat`, `fix`, `docs`, `refactor`, `test`,
   `chore`.
7. If there is nothing to commit, say so and move on. An empty day is normal.

### Rules that must not be broken

- Never run `git reset`, `git checkout`, `git push --force`, or `git clean`.
- Never delete a file to make the tree look clean. If a deletion is not yours,
  leave it and report it.
- Never commit a secret: a token, password, private key, or credential file.
  Report it instead.
- Do not push. Committing locally is the whole job.

## Job 2: consolidate the AI reflection archive

The archive is a topsailai-data object named `note--ai-reflection-archive`. It
holds one catalog file plus one file per lesson under `reflections/`. It grows
by one entry per lesson, so over time it accumulates near-duplicates and
entries that describe the same failure from different angles.

### Where it lives

```text
/work/hosts/.topsailai/data/object/2026/0828/1817/notes/topsailai/lessons/note--ai-reflection-archive/
├── note--ai-reflection-archive.md      # the catalog, one line per lesson
└── reflections/                        # one file per lesson
```

Read the catalog first. It is the index; the individual files hold the text.

### What to look for

1. **Exact duplicates.** Two entries stating the same rule with different
   filenames. Keep the clearer one, fold any unique detail into it, delete the
   other, and remove its catalog line.
2. **Mergeable pairs.** Two entries about the same failure mode where one is a
   special case of the other. Merge into the more general entry, keep the
   specific trigger as a clause, delete the narrower file.
3. **Contradictions.** Two entries giving opposite advice. This is a real
   defect: pick the one supported by evidence, and if neither is clearly right,
   report the conflict rather than guessing.
4. **Stale entries.** An entry whose rule no longer applies because the tool or
   convention it describes has changed. Report it; delete only when the reason
   is certain.

### How to merge safely

- Read both files in full before deciding. A filename is not the content.
- When merging, the surviving file must contain every distinct rule from both.
  Losing a rule while deleting its file is silent data loss.
- Update the catalog line to match the surviving file's name and description.
- Delete the absorbed file only after the survivor is written and read back.
- Keep the catalog and the `reflections/` folder in agreement: every catalog
  line names an existing file, and every file has a catalog line. Verify both
  directions at the end.

### Limits

- Do not merge more than five pairs in one run. A large rewrite is hard to
  review and easy to get wrong.
- Do not invent a new lesson. This job consolidates what exists; it does not
  add.
- Do not touch `snapshots/`. It is history.
- If the archive is already clean, say so. Reporting "nothing to merge" is a
  valid result and better than a forced merge.

## Output

Write a short report at the end of the run:

1. What was committed, with the commit hash, or that there was nothing to commit.
2. Which paths were added to `.gitignore` and why.
3. Any tracked binary found, listed by path, left untouched.
4. Which reflections were merged or deleted, naming both sides of each merge.
5. Any contradiction or stale entry found but not acted on, with the reason.

## Done when

The report answers all five points, and `git status --short` shows no staged
binary.
