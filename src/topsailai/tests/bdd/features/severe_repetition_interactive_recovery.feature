Feature: Interactive recovery from severe LLM repetition
  A repeated unusable response must not terminate an interactive session.
  Non-interactive callers must retain their fail-fast contract.

  Scenario: Interactive severe repetition abandons only the failed turn
    Given an LLM server returns two severely repetitive responses and then a fresh response
    When the interactive session receives a fresh message after the repetition verdict
    Then the severe repetition session remains alive for the fresh turn
    And the severe repetition scenario sends two old requests followed by one fresh request
    And the severe repetition verdict does not open the retry menu
    And the severe repetition failure hook runs exactly once

  Scenario: Non-interactive severe repetition remains fatal
    Given an LLM server returns two severely repetitive responses
    When severe repetition occurs without an interactive user
    Then the non-interactive severe repetition error escapes the turn loop
    And the non-interactive severe repetition scenario sends exactly two requests
