# topsailai_data Local Layout Best Practices

Author: DawsonLin

## Object folder rule

Every object is a folder whose name matches the object name. The folder must contain a file with the same name and a `.md` extension. This file is actual data, but its presence marks the folder boundary.

```text
hello/
  hello.md
```

## Time prefix

The first three directory levels under the root encode the creation time in local time:

```text
YYYY/MMDD/HHMM
```

Example for an object created on 2026-07-14 at 23:23:

```text
2026/0714/2323/hello
```

## Classify directories

After the time prefix, add directories to organize objects. Keep the total depth at most 11 levels. The time prefix uses 3 levels and the object folder uses 1 level, leaving 7 classify levels.

Good:

```text
2026/0714/2323/projects/demo/hello
```

Too deep:

```text
2026/0714/2323/a/b/c/d/e/f/g/h/hello  # 12 levels, exceeds limit
```

## Tag inheritance

Classify tag files apply recursively. Object tag files apply only to that object. Inherited and object tags are merged and deduplicated.

```text
2026/0714/2323/
  2323.tags            # applies to all objects under 2323/
  projects/
    projects.tags      # applies to all objects under projects/
    demo/
      demo.tags        # applies to all objects under demo/
      hello/
        hello.md
        hello.tags     # applies only to hello
```

Object `hello` receives the merged tags from `2323.tags`, `projects.tags`, `demo.tags`, and `hello.tags`.

## Tag file format

```text
# comment
work
important
```

Allowed comment prefixes after trimming leading whitespace: `#`, `;`, `//`, `--`.

## Do not scan inside object folders

Once a directory contains `{directory-name}.md`, the scanner stops there. Files like `hello/sub/hello.md` do not create a second object.

## Manual changes

Avoid creating or renaming object folders manually. Use the CLI so that `metadata.json`, the `.md` marker, and tag files stay consistent.
