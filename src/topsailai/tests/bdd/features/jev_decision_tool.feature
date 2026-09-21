Feature: JEV decision tool
  As an agent
  I want structured decisions based on the current runtime conversation
  So that semantic judgements include completed tool evidence without exposing system prompts

  Scenario: A noul decision uses sanitized runtime context over HTTP
    Given a private JEV-compatible server and configured tool
    And Agent2LLM history containing system user assistant and completed tool messages
    When the agent evaluates a noul refund question
    Then JEV receives the ordered eligible context without system messages
    And the completed tool interaction remains paired
    And the numeric noul result is returned unchanged

  Scenario: Missing credentials fail before transport
    Given a private JEV-compatible server without a configured API key
    And Agent2LLM history containing one user message
    When the agent evaluates a noul refund question
    Then the JEV request is rejected before network transport

  Scenario: Invalid upstream answers are rejected
    Given a private JEV-compatible server returning a mismatched answer
    And Agent2LLM history containing one user message
    When the agent evaluates a noul refund question
    Then the tool returns an invalid response status
