---
maintainer: AI
author: DawsonLin
---
# Quadratic time sorting and unstable equal keys

Scale acceptance found SortObjectsByTimePath performs N(N-1)/2 comparisons and can reverse equal-key entries despite its stability contract. At 100000 objects this costs about five billion comparisons. Replace pairwise swaps with standard-library stable sorting while preserving existing path comparison semantics; verify equal-key order in both directions and representative-scale sorting.

Status: resolved. `SortObjectsByTimePath` now uses `sort.SliceStable` with the unchanged `compareTimePath` semantics, so the comparison count drops from N(N-1)/2 to the standard-library stable sort cost and equal keys keep their input order. `TestCutoverSortStable` verifies equal-key order in both ascending and descending directions, and `TestCutoverSortScale` verifies ordering at 100000 objects in both directions.
