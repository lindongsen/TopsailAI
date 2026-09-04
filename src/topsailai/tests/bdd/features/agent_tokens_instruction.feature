Feature: Inspect current agent message tokens
  As an operator
  I want an agent instruction that estimates both current message layers
  So that I can understand runtime context usage before the next LLM request

  Scenario: The agent tokens instruction reports both layers and context capacity
    Given an active agent tokens instruction with distinct runtime and session messages
    When the operator invokes the registered agent tokens instruction
    Then the agent tokens report shows both current message layers
    And the agent tokens report shows configured context capacity
