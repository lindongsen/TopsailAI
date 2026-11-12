Feature: Bounded recovery guidance for null LLM responses
  As an agent user
  I want repeated blank provider responses to add bounded recovery guidance
  So that retries can recover without growing the conversation indefinitely

  Scenario: One continuous blank-response streak adds only one temporary message
    Given a null-response recovery request with repeated blank SSE responses before success
    When the null-response recovery request is sent
    Then requests before the threshold contain no temporary recovery message
    And every later retry contains exactly one temporary recovery message
    And the successful request restores the caller-owned conversation

  Scenario: Separate blank-response streaks cannot add duplicate recovery messages
    Given a null-response recovery request with two blank streaks separated by another provider error
    When the null-response recovery request is sent
    Then the second blank streak does not append another recovery message
    And the successful request restores the caller-owned conversation

  Scenario: Disabled recovery never changes retry messages
    Given a null-response recovery request with recovery disabled
    When the null-response recovery request is sent
    Then no retry contains a temporary recovery message
    And the successful request restores the caller-owned conversation

  Scenario Outline: Configured recovery content is bounded and blank content falls back to continue
    Given a null-response recovery request configured with "<configured>"
    When the null-response recovery request is sent
    Then every recovered retry contains exactly one "<expected>" message
    And the successful request restores the caller-owned conversation

    Examples:
      | configured      | expected        |
      | please continue | please continue |
      | <empty>          | continue        |
      | <whitespace>     | continue        |

  Scenario: Retry exhaustion still removes the temporary recovery message
    Given a null-response recovery request whose blank SSE responses exhaust retries
    When the null-response recovery request is sent
    Then the request ends with bounded retry exhaustion
    And every post-threshold exhausted retry contains exactly one temporary recovery message
    And the exhausted request restores the caller-owned conversation
