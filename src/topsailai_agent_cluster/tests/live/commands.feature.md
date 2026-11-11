---
maintainer: AI
author: DawsonLin
status: specification
---

# Feature: Management commands are authorized, durable, and evidence-preserving

## Background

Given the live environment passed
And a test-owned running session and exact generation are selected
And the CLI has a valid Server credential
And every command uses a fresh client-generated command ID unless the scenario tests duplication
And provider invocation and side effects can be observed without exposing message content

## Scenario CMD-LIVE-001: Send literal input exactly once

Given the Endpoint token grants `message.send`
When the CLI sends a literal test message containing spaces, Unicode, and leading dashes
Then the Server durably admits the command before acknowledging it
And the Endpoint invokes the provider exactly once with the literal message as one value
And the receipt reports the provider's real delivery boundary
And delivery is not described as Agent consumption or task completion

## Scenario CMD-LIVE-002: Inject side context without converting it to ordinary input

Given the Endpoint token grants `context.inject`
When the CLI submits literal side context
Then the provider receives the inject operation exactly once
And the receipt distinguishes `injection_queued` from ordinary input delivery
And no automatic retry occurs after uncertain delivery

## Scenario CMD-LIVE-003: Interrupt targets the exact running generation

Given the Endpoint token grants `execution.interrupt`
And the provider advertises defined interrupt semantics
When the CLI interrupts the selected session generation
Then the provider receives the exact session and generation selectors
And the receipt does not claim the Agent stopped unless exit was confirmed
And a stale generation is rejected without invoking the provider

## Scenario CMD-LIVE-004: Provider control action must be catalogued and authorized

Given the Endpoint token grants one configured `ctl.<action>` permission
And the Endpoint control catalog defines that exact action and payload schema
When the CLI submits a valid payload
Then the action reaches the configured provider command once
And the response preserves the control acknowledgement boundary
When the CLI submits an absent action or invalid payload
Then it is rejected before provider invocation

## Scenario CMD-LIVE-005: Sensitive control read needs its explicit permission

Given the control catalog exposes a sensitive conversation-read action
And the Endpoint token lacks that action's required permission
When the CLI invokes it
Then the Endpoint returns `policy_denied`
And no provider content is returned
And the provider is not invoked

## Scenario CMD-LIVE-006: Model selection changes only the exact session

Given the Endpoint token grants `agent.model.select`
And the live catalog contains a selected profile
When the CLI applies that profile to the exact session
Then the provider acknowledges the selection for that session
And an unrelated session retains its previous model
And the CLI does not treat catalog listing as selection authority

## Scenario CMD-LIVE-007: Command exec runs an allowlisted argv array

Given the Endpoint token grants `command.exec`
And the Endpoint-global allowlist contains the exact argv prefix
When the CLI executes a harmless read-only command in the test session workspace
Then no shell parses the request
And the process working directory is the resolved session workspace
And output, duration, and exit evidence are bounded
And only the requested command process group is owned by this invocation

## Scenario CMD-LIVE-008: Command exec rejects non-allowlisted argv

Given the Endpoint token grants `command.exec`
And the requested argv does not match the local allowlist
When the CLI submits the command
Then local execution policy rejects it
And no child process starts
And Endpoint access `allow-all` cannot override the allowlist

## Scenario CMD-LIVE-009: Command exec rejects path escape

Given the Endpoint token grants `command.exec`
And the argv prefix itself is allowed
When an argument uses an absolute path, parent traversal, or a symlink escape outside the session workspace
Then the operation fails closed
And no out-of-workspace file is read or modified
And no fallback to the Endpoint process working directory occurs

## Scenario CMD-LIVE-010: Endpoint policy refusal creates no provider side effect

Given the token lacks the requested management permission
When the CLI submits the command through the Server
Then Server admission does not imply Endpoint authorization
And the durable result converges to `policy_denied`
And effect certainty is `not_applied`
And provider invocation count does not change

## Scenario CMD-LIVE-011: Repeating the same command ID and intent is idempotent

Given a management command completed with a durable result
When the same issuer repeats the same command ID and canonical intent
Then the prior state or result is returned
And the provider is not invoked again
And rotating the transport Endpoint token alone does not change command identity

## Scenario CMD-LIVE-012: Reusing a command ID with changed intent is a conflict

Given a command ID is already bound to one canonical intent
When the same issuer submits that ID with a changed target, operation, payload, or expiry
Then the request is rejected as a conflict
And neither intent is re-executed

## Scenario CMD-LIVE-013: Cancel before dispatch prevents provider invocation

Given a command is durably admitted but not dispatched
When the authorized caller cancels it
Then the command becomes cancelled before execution
And provider invocation does not occur
And a later dispatch attempt cannot revive it

## Scenario CMD-LIVE-014: Cancel after Endpoint acceptance cannot claim effects stopped

Given the Endpoint has accepted or started provider invocation
When the caller requests cancellation
Then the result states that cancellation is too late or capability-specific
And it does not claim the provider effect stopped
And the final command evidence remains queryable

## Scenario CMD-LIVE-015: Caller timeout does not rewrite durable execution fact

Given provider execution lasts longer than the CLI wait budget
When the caller stops waiting
Then the CLI reports a wait timeout without changing command state
And a later status query returns the real terminal result
And the provider is not re-executed

## Scenario CMD-LIVE-016: Provider raw response remains separate and bounded

Given the provider returns a structured success or failure document
When the command reaches a terminal state
Then the service receipt and provider response are displayed as separate evidence
And the provider response is preserved verbatim up to the documented byte limit
And truncation is labelled
And provider stderr is not flattened into a generic success or failure message

## Scenario CMD-LIVE-017: Unsupported capability fails without substitution

Given the Endpoint does not advertise a requested operation
When the CLI submits that operation
Then the command is rejected as unsupported
And the Endpoint does not emulate it with a different destructive operation
And the provider is not invoked
