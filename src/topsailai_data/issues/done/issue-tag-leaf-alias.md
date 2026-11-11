---
maintainer: AI
author: DawsonLin
---

# Independent tag leaf alias validation

Status: resolved before new layout activation; local regression and focused race passed.

Verification: existing and dangling symlink fixtures preserve target bytes, leaf links and directory contents; package statement coverage 79.5%.

Trigger: reviewing independent tag storage for the coherent cutover found readObjectTags follows symlinks and writeObjectTags replaces them without rejecting the unsafe leaf.

Impact: a manually altered metadata tags leaf can redirect reads outside the intended object metadata. Existing directory checks alone do not validate the file leaf.

Action: require an existing tags leaf to be regular using Lstat before reading or replacing. Preserve missing-file semantics and cover dangling/existing symlinks, directories, alias target preservation and temporary cleanup.

Prevention: validate both directory components and individual metadata leaves, with direct alias fixtures rather than only malformed-content tests. The advisory-lock trust boundary excludes uncooperative concurrent filesystem replacement.
