Feature: Cached-token warning after context summarization
  As an operator
  I want context summarization to report a loss of provider cache reuse
  So that unexpected cached-token regressions are observable without false alarms

  Scenario: Decreased cached tokens print one exact warning
    Given a summarize cache-warning environment that will decrease cached tokens
    When context summarization sends a real request to its private provider
    Then the summarize cache-warning provider received the expected completion requests
    And the summary request contains the runtime context and summary instruction
    And the observed cached-token count decreased
    And one exact cached-token decrease warning was printed
    And context summarization returned a non-empty answer

  Scenario: Increased cached tokens do not print a warning
    Given a summarize cache-warning environment that will increase cached tokens
    When context summarization sends a real request to its private provider
    Then the summarize cache-warning provider received the expected completion requests
    And the summary request contains the runtime context and summary instruction
    And the observed cached-token count increased
    And no cached-token decrease warning was printed
    And context summarization returned a non-empty answer

  Scenario: Equal zero cached tokens do not print a warning
    Given a summarize cache-warning environment with equal zero cached tokens
    When context summarization sends a real request to its private provider
    Then the summarize cache-warning provider received the expected completion requests
    And the summary request contains the runtime context and summary instruction
    And the observed cached-token counts are both zero
    And no cached-token decrease warning was printed
    And context summarization returned a non-empty answer

  Scenario: Missing provider cache usage does not print a warning
    Given a summarize cache-warning environment without provider cache usage
    When context summarization sends a real request to its private provider
    Then the summarize cache-warning provider received the expected completion requests
    And the summary request contains the runtime context and summary instruction
    And the resulting cached-token count is unavailable
    And no cached-token decrease warning was printed
    And context summarization returned a non-empty answer
