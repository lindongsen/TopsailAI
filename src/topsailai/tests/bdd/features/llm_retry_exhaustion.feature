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

  Scenario: Operating-system SIGINT exits the real retry menu without replay
    Given a subprocess LLM retry scenario whose bounded cycle returns busy SSE responses
    When SIGINT is sent to the exact child blocked at the retry menu
    Then the SIGINT retry scenario exits with bounded exhaustion
    And the SIGINT retry scenario sent 18 unchanged requests without replay
    And the SIGINT retry scenario cleaned up its child and mock server resources

  Scenario: Missing runtime input exhausts without blocking
    Given an LLM retry scenario whose bounded request cycle returns only busy SSE responses
    When retry exhaustion has no runtime input capability
    Then the retry scenario terminates with a bounded exhaustion error
    And no retry exhaustion prompt was attempted
    And the retry scenario sent exactly 18 completion requests

  Scenario: Zero manual retry cycles stop after the initial request cycle
    Given an LLM retry scenario with zero manual retry cycles and only busy SSE responses
    When the configured retry boundary is exercised
    Then the configured retry boundary stops after 18 requests and zero menu prompts
    And every configured-boundary request body is identical

  Scenario: One manual retry cycle stops after exactly two request cycles
    Given an LLM retry scenario with one manual retry cycle and only busy SSE responses
    When the configured retry boundary is exercised
    Then the configured retry boundary stops after 36 requests and one menu prompt
    And every configured-boundary request body is identical

  Scenario: One manual retry cycle succeeds on its final permitted request
    Given an LLM retry scenario with one manual retry cycle that succeeds on request 36
    When the configured retry boundary is exercised
    Then the configured retry boundary succeeds on request 36 after one menu prompt
    And every configured-boundary request body is identical

  Scenario: Repeated Retry choices stop at the absolute request bound
    Given an LLM retry scenario whose configured retry budget returns busy SSE responses
    When the user repeatedly chooses Retry through every permitted manual cycle
    Then the retry scenario reaches its configured absolute request bound
    And every bounded retry request body is identical

  Scenario: Production default stops after seven manual retry cycles
    Given an LLM retry scenario using the default policy and only busy SSE responses
    When all seven default Retry choices are supplied
    Then the default retry policy stops after exactly 144 requests and seven menu prompts
    And every default-policy request body is parsed and identical
