---
maintainer: AI
author: DawsonLin
status: specification
---

# Feature: Detailed reads preserve provider truth and Endpoint authorization

## Background

Given a live Endpoint is online
And the selected test session is present in committed inventory
And the CLI has a valid Server credential
And each scenario uses an Endpoint token with only the permissions it names
And provider output and conversation evidence are bounded and redacted in the report

## Scenario OBS-LIVE-001: Read a bounded output snapshot

Given the token grants `output.read`
And the session has known recent output
When the CLI requests a bounded output snapshot
Then the response contains no more than the requested line and byte limits
And observation time is present
And truncation, scan limitation, and partial-result evidence are preserved
And the snapshot is not described as a live stream or complete history

## Scenario OBS-LIVE-002: Snapshot refusal remains policy_denied end to end

Given the token does not grant `output.read`
When the CLI requests an output snapshot
Then the Endpoint refusal is exposed as `policy_denied`
And it is not replaced with `unsupported`, `provider_error`, or an empty successful panel
And the provider is not invoked

## Scenario OBS-LIVE-003: Follow streams new records until the operator stops it

Given the token grants `output.follow`
And the provider advertises real follow support
When the operator starts standalone or interactive follow
And the provider writes new test-owned output
Then records arrive after the follow starts with observation timestamps
And repeated identical lines are preserved
When the operator uses the documented stop action
Then the follow child stops without stopping the Agent
And one clean terminal record is observed

## Scenario OBS-LIVE-004: Follow starts live rather than replaying complete history

Given the selected session has old output before follow begins
When the operator starts follow
Then the contract does not promise replay of all prior content
And newly written records are streamed in order
And any gap between a prior snapshot and follow start is not hidden

## Scenario OBS-LIVE-005: Follow refusal does not start a provider child

Given the token does not grant `output.follow`
When the CLI requests follow
Then the result code is `policy_denied`
And no provider follow process starts
And the result is not `unsupported`

## Scenario OBS-LIVE-006: Unsupported follow is explicit

Given the token grants `output.follow`
And the selected provider does not advertise follow support
When the CLI requests follow
Then the operation returns `unsupported`
And it does not degrade to a one-shot snapshot
And no successful stream is displayed

## Scenario OBS-LIVE-007: Read bounded conversation messages

Given the token grants `messages.read`
And the session contains known USER and ASSISTANT messages
When the CLI requests conversation messages with supported bounds
Then messages render as readable role-labelled blocks
And structured provider bodies are unwrapped when defined by the contract
And provider counts remain factual when display text is shortened
And sensitive content is not copied into the evidence report

## Scenario OBS-LIVE-008: Invalid message bounds fail before provider invocation

Given the token grants `messages.read`
When the CLI requests a negative bound, an above-maximum bound, or conflicting spellings
Then the request is rejected with a validation error
And no provider invocation occurs
And the error identifies the invalid field without disclosing message content

## Scenario OBS-LIVE-009: Read session history with deterministic bounds

Given the token grants `history.read`
And the provider has retained test history
When the CLI requests a valid history limit
Then no more than the requested number of records is returned
And records use stable provider session references and deterministic ordering
And unavailable history is distinguished from an empty successful history

## Scenario OBS-LIVE-010: Read the live model catalog without selecting a model

Given the token grants `agent.model.list` but not model selection
When the CLI lists model profiles for the target session
Then the live provider catalog is returned
And listing the catalog causes no model change
And a later selection attempt is refused with `policy_denied`

## Scenario OBS-LIVE-011: Query launch handlers and projects

Given the token grants `launch.query`
When the CLI requests launch handlers for the Endpoint
Then each live start-capable handler has an ID, display name, and revision
When the CLI requests projects for one handler
Then the response is bounded and associated with that handler
And a failed project query is not represented as a successful empty list

## Scenario OBS-LIVE-012: A restricted token cannot infer provider capability through timing

Given the token lacks the requested read permission
When it requests a read on an online supported Endpoint and on an unavailable or unsupported target
Then authorization is evaluated before provider capability or transport details are disclosed
And every applicable refusal is `policy_denied`
And observed response differences do not reveal provider reachability beyond the permitted inventory view

## Scenario OBS-LIVE-013: Large snapshot remains bounded across HTTP and WebSocket limits

Given the token grants `output.read`
And the session has output larger than the default WebSocket read size
When the CLI requests a snapshot within the documented maximum
Then the bounded response is delivered without corrupting the frame
And truncation is explicit when the requested or provider limit is reached
And memory use does not grow with the entire provider file

## Scenario OBS-LIVE-014: Detailed reads use exact target intersection

Given two provider sessions have similar display names or one reused identifier
When the CLI requests details with Endpoint, session, and generation selectors
Then only the exact selected resource is read
And stale, ambiguous, or mismatched selectors fail visibly
And the implementation does not retry with a looser selector or choose the newest row
