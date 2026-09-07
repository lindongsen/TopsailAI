Feature: Interactive recovery after LLM retry exhaustion
  As an interactive agent user
  I want a bounded LLM request failure to offer explicit recovery actions
  So that I can retry the same request, return to chat, or exit safely

  Scenario: Retry resends the identical LLM request inside one chat call
    Given an LLM retry scenario whose first request cycle returns busy SSE responses and then succeeds
    When the user enters an invalid exhaustion choice and then chooses Retry
    Then the retry scenario returns the successful provider response
    And the retry scenario sent exactly 19 completion requests
    And every retry request body is identical
    And the invalid retry choice issued no provider request

  Scenario: Back abandons the failed turn and sends only fresh chat input
    Given an LLM retry scenario whose first request cycle returns busy SSE responses and then succeeds
    When the continuous chat user enters an invalid choice and then chooses Back
    Then the Back scenario ran the old and fresh Agent turns exactly once each
    And the Back scenario ignored blank and formatting-empty fresh input
    And the Back scenario sent 18 old requests followed by one fresh request
    And the invalid Back choice issued no provider request

  Scenario: Continuous chat can exit after exhaustion
    Given an LLM retry scenario whose bounded request cycle returns only busy SSE responses
    When the continuous chat user chooses Exit after exhaustion
    Then the retry scenario terminates with a bounded exhaustion error
    And the continuous exhaustion menu includes Back
    And the retry scenario sent exactly 18 completion requests

  Scenario: Finite execution cannot return to chat
    Given an LLM retry scenario whose bounded request cycle returns only busy SSE responses
    When the finite execution user chooses Exit after exhaustion
    Then the retry scenario terminates with a bounded exhaustion error
    And the finite exhaustion menu omits Back
    And the retry scenario sent exactly 18 completion requests

  Scenario: End of input selects Exit
    Given an LLM retry scenario whose bounded request cycle returns only busy SSE responses
    When the retry exhaustion input reaches EOF
    Then the retry scenario terminates with a bounded exhaustion error
    And the retry scenario sent exactly 18 completion requests

  Scenario: Keyboard interruption selects Exit
    Given an LLM retry scenario whose bounded request cycle returns only busy SSE responses
    When the retry exhaustion input is interrupted by the keyboard
    Then the retry scenario terminates with a bounded exhaustion error
    And the retry scenario sent exactly 18 completion requests

  Scenario: Missing runtime input exhausts without blocking
    Given an LLM retry scenario whose bounded request cycle returns only busy SSE responses
    When retry exhaustion has no runtime input capability
    Then the retry scenario terminates with a bounded exhaustion error
    And no retry exhaustion prompt was attempted
    And the retry scenario sent exactly 18 completion requests

  Scenario: Repeated Retry choices stop at the absolute request bound
    Given an LLM retry scenario whose configured retry budget returns busy SSE responses
    When the user repeatedly chooses Retry through every permitted manual cycle
    Then the retry scenario reaches its configured absolute request bound
    And every bounded retry request body is identical
