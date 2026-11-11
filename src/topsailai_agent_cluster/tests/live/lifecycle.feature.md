---
maintainer: AI
author: DawsonLin
status: specification
---

# Feature: Agent lifecycle and drive controls preserve ownership boundaries

## Background

Given the provider advertises the lifecycle capability used by the scenario
And the Endpoint token grants only the named lifecycle or drive operation
And the target project and sessions are test-owned
And the operator recorded unrelated Agents that must remain untouched
And every destructive operation has explicit human confirmation

## Scenario LIFE-LIVE-001: Start with a live handler and exact revision

Given launch query returned a start-capable handler, revision, and approved project
And the Endpoint token grants `agent.start`
When the CLI starts an Agent with a literal initial task
Then one start command is admitted for the exact Endpoint and handler revision
And the provider reports its real submission evidence
And the result does not claim readiness or task completion
And the literal task is forwarded as one value without shell interpretation

## Scenario LIFE-LIVE-002: Start with a stale profile revision is rejected

Given the live handler revision changed after the operator viewed it
When the CLI starts with the stale revision
Then the Endpoint rejects the request before provider launch
And no Agent is created
And the caller must query launch options again

## Scenario LIFE-LIVE-003: Successful start performs one Endpoint-scoped fresh collection

Given the provider accepted the start request
When the CLI performs its post-start refresh
Then only the target Endpoint is refreshed
And the launch result remains successful if the convenience refresh fails
And the command does not poll repeatedly
And a newly visible session is shown using its standard ID

## Scenario LIFE-LIVE-004: Submitted session may be temporarily not visible

Given the provider accepted a background start
And the immediate collection does not yet include the new session
When the CLI renders the result
Then it reports `session submitted but not yet visible`
And it does not report a launch failure
And the next periodic or operator-forced collection may reveal the session

## Scenario LIFE-LIVE-005: Resume exact durable session

Given a stopped or resumable test-owned session appears in provider history
And the token grants `agent.resume`
When the CLI resumes it using its exact durable reference
Then the provider receives one resume request
And the resulting running session maps back to the intended history entry
And resume is not emulated by creating an unrelated fresh conversation

## Scenario LIFE-LIVE-006: Stop exact generation without confusing interrupt

Given a running test session has a known generation
And the token grants `agent.stop`
When the operator confirms stop
Then the provider receives the exact stop request once
And a signal-sent receipt is not reported as confirmed exit
And confirmed provider exit is reported separately
And no turn-interrupt operation is substituted

## Scenario LIFE-LIVE-007: Stop without generation fails closed

Given the selected session lacks a valid generation selector
When the CLI requests stop
Then the command is rejected before provider invocation
And the CLI does not fall back to a PID, display row, or newest session

## Scenario LIFE-LIVE-008: Stale generation cannot stop a replacement Agent

Given an old session identity was replaced by a new generation
When the CLI submits stop for the old generation
Then the request is rejected as stale or mismatched
And the replacement Agent remains running
And no looser selector retry occurs

## Scenario LIFE-LIVE-009: Start and stop a drive controller without owning the Agent

Given a running test session supports drive control
And the token grants `agent.drive.start` and `agent.drive.stop`
When the operator confirms drive start
Then the provider reports the real controller outcome
And the Agent remains independently managed
When the operator stops the drive controller
Then only the controller is stopped
And the Agent remains running

## Scenario LIFE-LIVE-010: Drive state is an inventory observation

Given the provider reports a drive summary
When the CLI reads session details
Then drive state is shown as one of `none`, `running`, `stale`, `exited`, `failed`, or `unknown`
And the read does not create a command journal entry
And an unverified controller is never rendered as running

## Scenario LIFE-LIVE-011: Stopping a residual drive record does not require a live Agent target

Given the provider has a residual controller record whose process is already gone
When the CLI requests `agent.drive.stop` for that record
Then the provider may clean or confirm the residual record
And the request does not require or stop the Agent process
And the result preserves `already_stopped`, `stopped`, or unconfirmed provider evidence

## Scenario LIFE-LIVE-012: Endpoint restart does not stop or restart Agents

Given a test Agent is running independently of the Endpoint
When the exact Endpoint process is restarted in an approved window
Then the Agent remains in its provider-managed lifecycle
And the Endpoint reconnects and rediscovers it through the provider CLI
And the Endpoint does not adopt, reparent, automatically restart, or terminate the Agent

## Scenario LIFE-LIVE-013: Unsupported lifecycle operation is explicit

Given a provider does not advertise start, resume, stop, or drive support used by the request
When the CLI requests that operation
Then the result is unsupported or a precise integration gap
And no substitute operation runs
And lack of support is not reported as successful submission
