Feature: LLM provider request statistics
  As an operator
  I want each real LLM provider request to update visible execution-context statistics
  So that I can observe total request volume and rolling requests per minute

  Scenario: A real non-streaming LLM request updates total and RPM statistics
    Given an LLM request statistics environment with a private mock LLM server
    When one non-streaming LLM request is sent through the real client
    Then the LLM request statistics mock server received exactly 1 completion request
    And the LLM request statistics request body contains the user message
    And the execution-context LLM total and RPM each increased by 1
    And each Thinking log has exactly one complete LLM request statistics output immediately before it

  Scenario: An invalid real LLM response increments request failures
    Given an LLM request statistics environment with a private mock LLM server
    When one invalid non-streaming LLM response is received through the real client
    Then the LLM request statistics mock server received exactly 1 completion request
    And the execution-context LLM total and failures each increased by 1
    And the execution-context LLM successes and content errors did not increase
    And each Thinking log has exactly one complete LLM request statistics output immediately before it

  Scenario: An unknown native tool increments content errors independently
    Given an LLM request statistics environment with a private mock LLM server
    When one unknown native tool call is received through the real client
    Then the LLM request statistics mock server received exactly 2 completion requests
    And the execution-context LLM total and successes each increased by 2
    And the execution-context LLM failures did not increase
    And the execution-context LLM content errors increased by 1
    And each Thinking log has exactly one complete LLM request statistics output immediately before it
