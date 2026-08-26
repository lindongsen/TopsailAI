@bdd @noninteractive
Feature: Cached token statistics against the LLM mock server
  As a user retaining Agent2LLM messages to reuse server-side cache
  I want cached-token statistics to reflect each request's real cache state
  So that I can distinguish cache hits, misses, and not-yet-measured state

  Background:
    Given a TopsailAI environment connected to the LLM mock server

  Scenario: Identical request reuses the full cached prefix
    Given a conversation whose leading messages form a stable prefix
    When the same leading prefix is sent again
    Then the response reports a non-zero cached token count
    And the measured uncached-token statistic is non-negative

  Scenario: Changing the leading message breaks the cache prefix
    Given a conversation with a previously cached leading prefix
    When the leading message differs from the cached prefix
    Then the response reports zero cached tokens
    And the measured uncached-token statistic is non-negative

  Scenario: Summarization marks the cache state as not measured
    Given a conversation that has accumulated measurable cached tokens
    When summarization rebuilds the Agent2LLM messages
    Then the cached-token statistic is reported as unknown rather than zero
    And the uncached-token statistic is not reported as a negative number

  Scenario: A new request after summarization re-establishes the cache state
    Given summarization has just marked the cache state as unknown
    When a new request completes against the mock server
    Then the cached-token statistic reflects the new request's real hit or miss
    And the measured uncached-token statistic is non-negative
