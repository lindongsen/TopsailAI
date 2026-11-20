---
maintainer: AI
author: DawsonLin
severity: low
status: open
created: 2026-11-20
---

# The packaging summary contradicts itself about the node id

## Symptom

`make package-stateless` prints two sentences that cannot both be true:

```
Stateless mode is compiled in, so the binary writes nothing: no config directory,
no identity file, no credential file. The node id and the credential are generated
in memory on every start, so the address changes each time the process starts. The
values in the env file are the ones this build generated, and they are the ones the
binary will use, because they are compiled in as seeds.
```

The first sentence says the address changes on every start. The second says the
env-file values are the ones the binary will use. A reader cannot tell whether the
env file must be re-read after a restart.

## Measured behaviour

The second sentence is correct. The compiled values are seeds, so the id is stable
across restarts until `regenerate id` runs on the target.

Three consecutive starts of a Linux stateless build:

```
run1 pid=3612751 id=node_wkpnpp6grwe7zdyalaugvjq6ji
run2 pid=3612972 id=node_wkpnpp6grwe7zdyalaugvjq6ji
run3 pid=3613162 id=node_wkpnpp6grwe7zdyalaugvjq6ji
```

The env file for that build held the same value, and a CLI call using only the
env-file values returned `rc=0`.

## Why it matters

The sentence decides an operator's procedure. If the address changed on every
start, the env file would be stale the moment the process restarted, and every CLI
call would answer `node_offline` until someone re-read the file. An operator who
believes that will either re-read the file needlessly or, worse, conclude that a
`node_offline` answer is normal.

## Cause

The sentence was written from the design intent of stateless mode ("nothing is
persisted") rather than from the seed behaviour that was implemented. The two are
different: nothing is *written*, but the compiled seed is *used*, so the value is
reproducible.

## Fix

Replace the sentence with what the code does: the id and the credential are
generated in memory from the compiled seeds, so they are the same on every start
until `regenerate id` runs on the target, and the env file stays valid.

## Detection gap

No test reads the packaging summary. The summary is printed by
`packaging/build-package.sh` and asserted by nothing, so a sentence that
contradicts the code passes every check. The same class as
`LEARN.md`'s "a documented command is a claim that must be executed": a printed
claim is a claim, and this one was never compared with a measurement.
