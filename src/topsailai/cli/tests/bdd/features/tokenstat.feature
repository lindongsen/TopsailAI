@bdd @noninteractive
Feature: TokenStat observability
  As an operator observing LLM activity
  I want TokenStat snapshots and session totals to remain accurate
  So that token usage, cache usage, and first-byte latency are trustworthy

  Background:
    Given a TopsailAI environment connected to the LLM mock server

  Scenario: A real request emits the complete TokenStat snapshot contract
    Given a conversation whose leading messages form a stable prefix
    When the TokenStat snapshot is emitted
    Then the snapshot contains every TokenStat observability field
    And the snapshot token and text fields are integer measurements
    And the empty first-byte fields are reported as unknown

  Scenario: Response usage exposes explicit fields after a real non-streaming response
    Given a conversation whose leading messages form a stable prefix
    When the conversation is sent to the LLM mock server
    Then the mock server receives exactly two non-streaming requests with the scenario message
    And TokenStat current tokens equal the response prompt tokens
    And TokenStat explicit current usage equals the response prompt and completion usage
    And TokenStat total tokens count the request only once
    And the non-streaming response is output before the token summary
  Scenario: First-byte samples are converted and rounded in the snapshot
    Given first-byte latency samples of 100.1234567, 200.9876543, and 50.5555555 milliseconds
    When the TokenStat snapshot is emitted
    Then first-byte latency is reported as 0.117 average, 0.201 maximum, and 0.051 minimum seconds

  Scenario: Multiple agents accumulate token deltas in one shared session
    Given a shared session for TokenStat accumulation
    When one agent reports 120 tokens with 40 cached tokens
    And another agent reports 80 tokens with 15 cached tokens
    Then the shared session totals are 200 tokens and 55 cached tokens

  Scenario: A one-shot AgentChat prints its final session summary after the answer
    When one AgentChat turn completes against the LLM mock server
    Then the one-shot answer is output once before one final session token summary

  Scenario: Cached usage cannot make uncached tokens negative
    Given a TokenStat measurement of 20 tokens with 30 cached tokens
    When the TokenStat snapshot is emitted
    Then the measured uncached-token statistic is non-negative
