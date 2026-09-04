Feature: Tool observation content placement
  As an agent user
  I want content moved from tool-module OBSERVATION to PROMPT
  So that the moved content is supplied as system context

  Scenario: Moved tool content is sent only as a system message
    Given a tool prompt scenario with a private mock LLM server
    When the agent sends one task through the real LLM client
    Then the tool startup marker is present in a system message
    And the tool startup marker is absent from every user message
    And the tool prompt mock server received exactly 1 completion request

  Scenario: Manager delegation does not duplicate startup context in user messages
    Given a manager and subagent prompt scenario with a private mock LLM server
    When the manager delegates one task through the real subagent tool
    Then the nested agent requests contain startup context only in system messages
    And the nested agent requests contain no startup marker in user messages
    And the nested tool prompt mock server received exactly 3 completion requests
