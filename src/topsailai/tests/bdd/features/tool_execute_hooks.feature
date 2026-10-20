Feature: Approved tool execution is observable without changing provider history
  The user can monitor a single approved tool call without exposing its values
  or changing the result sent back to the language model.

  Scenario Outline: Native tool outcomes retain their paired result
    Given a private HTTP tool execution environment with outcome "<outcome>"
    When the provider requests the configured tool
    Then approval precedes exactly the matching tool execution observations
    And the next provider request contains the original paired tool result

    Examples:
      | outcome |
      | success |
      | error   |
