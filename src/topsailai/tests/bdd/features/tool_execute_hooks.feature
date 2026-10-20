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

  Scenario Outline: Streamed native tool outcomes retain metadata-only observations and paired results
    Given a private SSE tool execution environment with outcome "<outcome>"
    And the provider streams a native call with arguments split across three deltas
    When the provider requests the configured tool
    Then the client consumes native SSE deltas and assembles the configured tool arguments
    And approval precedes exactly the matching tool execution observations
    And exactly the matching terminal observation exposes only permitted metadata
    And the next streaming provider request contains the original paired tool result

    Examples:
      | outcome |
      | success |
      | error   |
