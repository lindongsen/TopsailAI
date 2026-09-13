Feature: Team-level shared values reach Member LLM requests
  As a team operator
  I want shared team values composed once for every Member entry
  So that Agent and Chat workers receive consistent team context

  # Acceptance: issues/issue-team-level-values-support.md
  Scenario: A directly started Member Agent receives shared Team values once
    Given a direct Member team with non-empty shared values and a private mock LLM server
    When the direct Member Agent sends one real LLM request
    Then the Team values mock server received exactly 1 completion requests
    And the captured system prompt contains the shared Team marker exactly once
    And every captured level-one heading is unique

  Scenario: A plugin-precomposed Member does not duplicate shared Team values
    Given a plugin-precomposed Member team and a private mock LLM server
    When the plugin-precomposed Member sends one real LLM request
    Then the Team values mock server received exactly 1 completion requests
    And the captured system prompt contains the shared Team marker exactly once
    And the captured system prompt contains the AI Team heading exactly once
    And every captured level-one heading is unique

  Scenario: Explicit direct composition overrides matching plugin provenance
    Given a plugin-precomposed Member team and a private mock LLM server
    When the Member sends one real LLM request with precomposed explicitly false
    Then the Team values mock server received exactly 1 completion requests
    And the captured system prompt contains the shared Team marker exactly once
    And every captured level-one heading is unique

  Scenario: Equal user headings from independent prompt segments are preserved
    Given a direct Member team with non-empty shared values and a private mock LLM server
    When independent prompt segments with the same AI Team heading are sent
    Then the Team values mock server received exactly 1 completion requests
    And the captured system prompt contains both same-heading policy markers
    And the captured system prompt contains the AI Team heading exactly 2 times

  Scenario: Team Agent and Team Chat send equivalent shared context
    Given a direct Member team with non-empty shared values and a private mock LLM server
    When Team Agent and Team Chat each send one real LLM request
    Then the Team values mock server received exactly 2 completion requests
    And both captured system prompts contain the same shared Team marker once
    And the Team Chat output requirement follows its canonical Member system prompt

  Scenario Outline: Missing or empty shared Team values preserve Member requests
    Given a direct Member team whose shared values are <shared_values_state> and a private mock LLM server
    When the direct Member Agent sends one real LLM request
    Then the Team values mock server received exactly 1 completion requests
    And the captured system prompt omits the shared Team marker

    Examples:
      | shared_values_state |
      | missing             |
      | empty               |

  Scenario: Unreadable shared Team values fail before provider I/O
    Given a direct Member team with unreadable shared values and a private mock LLM server
    When the direct Member prompt is resolved
    Then shared Team prompt resolution fails closed
    And the Team values mock server received exactly 0 completion requests
