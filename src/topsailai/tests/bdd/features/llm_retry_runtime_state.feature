Feature: Agent runtime state for repeated LLM request failures
  As an agent operator
  I want repeated provider failures to publish bounded runtime state
  So that faults are observable without polluting conversation context

  Scenario: The third failed attempt activates retry state until success
    Given an Agent-owned request with three SSE failures before a held success
    When the request reaches the held successful attempt
    Then one retry runtime state is active with failed count 3
    And provider messages contain no runtime state data
    When the held successful attempt is released
    Then the request succeeds with no active retry state
    And runtime history records one recovered retry state

  Scenario: Later failures update one active state
    Given an Agent-owned request with five SSE failures before a held success
    When the request reaches the held successful attempt
    Then one retry runtime state is active with failed count 5
    And its revision is greater than one
    When the held successful attempt is released
    Then the request succeeds with no active retry state

  Scenario: A request below the threshold creates no history
    Given an Agent-owned request with two SSE failures before success
    When the retry runtime request completes
    Then no retry runtime state or history exists

  Scenario: Retry exhaustion settles failed bounded history
    Given an Agent-owned request that exhausts all automatic SSE retries
    When the retry runtime request completes
    Then retry exhaustion leaves no active state
    And runtime history records one failed retry state

  Scenario: Direct LLM chat retains retry behavior without Runtime Data
    Given a direct request with three SSE failures before success
    When the retry runtime request completes
    Then the direct request succeeds without Runtime Data publication
