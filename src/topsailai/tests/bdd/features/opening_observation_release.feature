Feature: Release the opening observation after summarization
  As an agent operator
  I want an oversized startup observation to be released once a summary exists
  So that a large startup context cannot stay pinned in every later request


  Scenario: An oversized opening observation is released after the summary
    Given an opening observation release with ratio 0.3 and a token threshold of 1000
    And a large startup observation
    When the user-facing summarization completes
    Then the opening observation is gone from memory
    And the opening observation is gone from storage
    And the summary request reached the provider exactly once

  Scenario: A small opening observation stays pinned
    Given an opening observation release with ratio 0.3 and a token threshold of 1000
    And a small startup observation
    When the user-facing summarization completes
    Then the opening observation is still in memory
    And the opening observation is still in storage

  Scenario: A zero ratio disables the release
    Given an opening observation release with ratio 0 and a token threshold of 1000
    And a large startup observation
    When the user-facing summarization completes
    Then the opening observation is still in memory
    And the opening observation is still in storage

  Scenario: A skipped summarization never releases the observation
    Given an opening observation release with ratio 0.3 and a token threshold of 1000
    And a large startup observation
    When the user-facing summarization is skipped
    Then the opening observation is still in memory
    And the opening observation is still in storage
    And no release warning was printed
    And no release event was recorded

  Scenario: A later user-role tool observation survives the release
    Given an opening observation release with ratio 0.3 and a token threshold of 1000
    And a large startup observation
    And a later user-role tool observation
    When the user-facing summarization completes
    Then the startup observation is gone from storage
    And the later user-role tool observation is still in storage

  Scenario: The release prints a warning and records an event
    Given an opening observation release with ratio 0.3 and a token threshold of 1000
    And a large startup observation
    When the user-facing summarization completes
    Then a release warning names the removed count and the decision inputs
    And a release event records the decision inputs

  Scenario: The agent-layer summarization also releases the observation
    Given an opening observation release with ratio 0.3 and a token threshold of 1000
    And a large startup observation
    When the agent-layer summarization completes
    Then the opening observation is gone from agent memory
    And the opening observation is gone from storage
    And the summary request reached the provider exactly once

  Scenario: The in-memory branch releases the observation without a session
    Given an opening observation release with ratio 0.3 and a token threshold of 1000
    And a large startup observation
    When the user-facing summarization completes without a session
    Then the opening observation is gone from memory
    And the opening observation is still in storage
    And the summary request reached the provider exactly once
