Feature: A JSON array of bare scalars becomes usable thought steps
  As a user whose model answered with a JSON array of plain strings
  I want the parsed steps to stay usable instead of crashing the turn
  So that the model's text is preserved and the agent loop can continue

  Scenario Outline: Parse a bare-scalar step array through a streamed provider request
    Given a provider that streams a bare-scalar step array in "<mode>" tool mode
    When the conversation requests a streamed continuation
    Then the parsed steps are all objects with a thought step name
    And the model text is preserved in the thought step
    And the provider receives exactly one streamed request

    Examples:
      | mode       |
      | native     |
      | non-native |
