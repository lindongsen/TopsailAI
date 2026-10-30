Feature: Mixed JSON conversation history remains usable
  As a user continuing a conversation
  I want JSON tool arguments alongside a step marker to remain intact
  So that the next LLM request succeeds instead of failing before it is sent

  Scenario Outline: Continue mixed JSON history through a streamed provider request
    Given a mixed JSON history conversation using "<mode>" tool mode
    When the conversation requests a streamed continuation
    Then the mixed JSON conversation receives the provider reply
    And the provider receives exactly one streamed request with the original history

    Examples:
      | mode       |
      | native     |
      | non-native |
