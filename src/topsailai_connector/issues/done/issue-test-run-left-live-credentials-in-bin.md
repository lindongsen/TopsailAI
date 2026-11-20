---
maintainer: AI
author: DawsonLin
status: fixed
created: 2026-11-20
updated: 2026-11-20
severity: high
---

# A test run left live credentials in the folder artifacts are copied from

## Symptom

After `make check`, `bin/` held six files named `env.<timestamp>`:

```
bin/env.20261120011012   997 bytes
bin/env.20261120011015   980 bytes
bin/env.20261120011018   979 bytes
bin/env.20261120011214   997 bytes
bin/env.20261120011216   980 bytes
bin/env.20261120011217   979 bytes
```

Each one held a node id, a key id and a node credential secret that never expires.

## Root cause

`tests/e2e/verify_package.sh` runs `make package` five times to exercise both
packaging modes, the filesystem-root opt-in and the unrecognised-value refusal. None
of those invocations overrode `BIN_DIR`, so `write_env_file()` wrote into the
repository's `bin/` directory, which is the folder an operator copies artifacts from
and the folder a release build writes to.

The packaging script had no way to separate "where the artifact goes" from "where the
credential record goes". One variable decided both, so a caller who wanted the
artifact in a scratch folder had to move the artifact too, and a caller who left the
default got a credential in the deliverable folder.

## Detection gap

`bin/` is git-ignored, so `git status` stayed clean and no review step saw the files.
The e2e script asserted that the artifact existed and that the bundle behaved
correctly; nothing asserted where the credential record went, because the record was
a new artifact and no test had been written about its location.

The leak was found by listing `bin/` during cleanup, not by any assertion. A test that
creates a file must assert where that file is, or the location is unowned.

## Fix

`ENV_DIR` is now a separate knob, defaulting to `BIN_DIR`:

```bash
ENV_DIR=${ENV_DIR:-$BIN_DIR}
ENV_PATH=$(absolute "$ENV_DIR")
```

`write_env_file()` writes to `ENV_PATH`, the Makefile passes `ENV_DIR` through the
`package` target, and `tests/e2e/verify_package.sh` sets `ENV_DIR` to a scratch folder
under `.tmp/` for every invocation.

The six leaked files were deleted with a printed log naming each path and its size.

## Prevention

A test that runs a packaging step must redirect every output the step produces, not
only the artifact it asserts about. The credential record is an output, and it is the
one output that must never land in a deliverable folder.

Assert the absence, not only the presence. After `make check`, `ls bin/env.*` must
return nothing; that assertion is what proves the leak is closed, and it is the one
assertion a reviewer can run in a second.

Keep "where the artifact goes" and "where the secret goes" as two variables whenever
one of them is a deliverable and the other is a record. A single variable forces every
caller to choose between a correct artifact location and a safe secret location.
