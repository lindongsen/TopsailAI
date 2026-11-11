---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
---

# Active session messages removed while creating an analysis session

## Status

Resolved in the working tree; strict deletion checks and regression coverage are complete.

## Observed impact

Session `wa-8a43da1e4204` lost its database row and nearly all message associations while its worker was still active. Its stdout and event files remained on disk. The database deletion occurred immediately after analysis session `sad-06874fb1640d` was created.

## Confirmed root cause

Creating the analysis session called `DefaultSessionManager.create_session()`, which triggered automatic retention eviction. The cleanup process checked the target PID only in its own host or PID namespace. Because it could not see the remote live PID, the old activity probe classified the owner as stopped and authorized deletion. The analysis-session completion cleanup did not pass the wrong session ID.

The design defect was broader than retention: local PID absence was treated as sufficient deletion evidence without proving that the metadata belonged to this host and represented a finalized owner. Any deletion caller using the same probe could therefore misclassify a remote or namespace-isolated active session.

## Resolution

The shared `SessionActivityProbe` now provides the strict authorization used by automatic retention, explicit database deletion, age cleanup, message cleanup, CLI cleanup, and disk-file cleanup:

- A responding control endpoint or a live local PID protects the session.
- Any endpoint or PID inspection failure returns unknown and blocks deletion.
- Every discovered owner PID must have exactly one stable regular metadata file.
- Metadata must match the session ID and PID, identify the current host, and contain a finalized status: `completed`, `error`, or `interrupted`.
- Foreign, missing, malformed, changing, `running`, or future unknown metadata blocks deletion.
- Database and disk deletion recheck activity immediately before mutation.

This is intentionally fail-closed: inability to prove that every owner is safely stopped preserves the session.

## Verification

Regression coverage confirms:

- Foreign owners remain protected when their PID is absent locally.
- A `running` owner remains protected even when hostnames match but PID namespaces differ.
- Missing or invalid host identity blocks deletion.
- A live control endpoint protects an owner before PID inspection.
- Endpoint inspection failures block deletion.
- Auxiliary records cannot borrow another PID's metadata.
- Creating an excess session preserves a foreign active session, its message, and its session-message association.
- Finalized local stopped owners remain eligible for cleanup.

The direct activity, cleanup guard, manager contract, cleanup edge, pause-marker, and retention suites pass: `153 passed`.
