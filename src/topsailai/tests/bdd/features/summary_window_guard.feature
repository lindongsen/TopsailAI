Feature: Sliding-window summary guard
  As an agent operator
  I want a turn to end when recent LLM traffic is dominated by summary requests
  So that a runaway summarization loop cannot burn tokens indefinitely


  Scenario: Three summary requests inside the window stay below the limit
    Given a summary window guard with a window of 10 requests and a limit of 3
    When three summary requests are sent through the provider boundary
    Then the summary window guard does not terminate the turn
    And the provider received exactly 3 requests
    And the summary window recorded 3 summary requests

  Scenario: The fourth summary request inside the window terminates the turn
    Given a summary window guard with a window of 10 requests and a limit of 3
    When four summary requests are sent through the provider boundary
    Then the summary window guard terminates the turn
    And the termination names 4 summary requests in the last 10 LLM requests
    And the provider received exactly 3 requests
    And the summary window recorded 4 summary requests

  Scenario: Ordinary agent traffic never terminates the turn
    Given a summary window guard with a window of 10 requests and a limit of 3
    When twelve ordinary agent requests are sent through the provider boundary
    Then the summary window guard does not terminate the turn
    And the provider received exactly 12 requests
    And the summary window holds only ordinary agent requests

  Scenario: Interleaved summary traffic terminates once the limit is exceeded
    Given a summary window guard with a window of 10 requests and a limit of 3
    When summary requests are interleaved with ordinary agent requests
    Then the summary window guard terminates the turn
    And the provider received exactly 6 requests
    And the summary window recorded 4 summary requests

  Scenario: A zero limit disables the guard
    Given a summary window guard with a window of 10 requests and a limit of 0
    When six summary requests are sent through the provider boundary
    Then the summary window guard does not terminate the turn
    And the provider received exactly 6 requests

  Scenario: One summary request retried many times terminates the turn
    Given a summary window guard with a window of 10 requests and a limit of 3
    When one summary request is retried twelve times by the provider
    Then the summary window guard terminates the turn
    And the termination names 4 summary requests in the last 10 LLM requests
    And the provider received exactly 9 requests
    And the summary window recorded 4 summary requests
