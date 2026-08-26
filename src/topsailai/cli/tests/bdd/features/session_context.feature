@bdd @noninteractive
Feature: Session context lifecycle and cache behavior
  As a user running a long session
  I want context compression to interact predictably with server-side caching
  So that cache reuse degrades gracefully without inventing cache state

  Background:
    Given a TopsailAI session connected to the LLM mock server

  Scenario: Compression lowers the achievable cache hit
    Given a session with a fully cached compressible context
    When the context is summarized and requested again
    Then the achievable cached-token hit is lower than before compression
    And the post-compression cache usage matches the mock server result
    And the uncached-token statistic remains non-negative

  Scenario: Nothing compressible leaves the cache state unchanged
    Given a session with measured cache usage and no compressible messages
    When summarization is attempted for that session
    Then no session summarization occurs
    And the cached-token statistic remains in its prior state
    And the uncached-token statistic remains non-negative
