@bdd @noninteractive
Feature: Agent2LLM runtime messages are the summary request source
  As an operator relying on context summarization
  I want the summary LLM to receive the complete Agent2LLM runtime sequence
  So that ephemeral reasoning is not replaced by persisted User2Agent history

  Scenario: Runtime summarization transmits the complete pre-summary Agent2LLM sequence
    Given a runtime-summary mock server and distinct Agent2LLM and User2Agent messages
    When forced runtime Agent2LLM summarization crosses the real HTTP boundary
    Then the runtime-summary mock server receives exactly one request
    And the runtime-summary request has one appended instruction message
    And the runtime-summary request prefix hash equals the pre-summary Agent2LLM hash
    And the runtime-summary request ends with the appended summary instruction
    And runtime-summary source fallback emits no warning
