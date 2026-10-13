Feature: Optional human factual context loading
  As an agent operator
  I want to control automatic USER.md loading
  So that startup context can omit human factual context when needed

  Scenario: USER.md is loaded by default at the real LLM boundary
    Given a USER.md startup context scenario with loading enabled
    When the agent sends one real LLM request
    Then the USER.md mock server received exactly 1 completion request
    And the captured request contains the USER.md marker
    And the captured request contains the explicit context marker
    And the USER.md load switch is latched to 0
    When the agent sends a second real LLM request
    Then the USER.md mock server received exactly 2 completion requests
    And the second captured request omits the USER.md marker
    And the second captured request contains the explicit context marker

  Scenario: USER.md loading can be disabled without disabling explicit context
    Given a USER.md startup context scenario with loading disabled
    When the agent sends one real LLM request
    Then the USER.md mock server received exactly 1 completion request
    And the captured request omits the USER.md marker
    And the captured request contains the explicit context marker
