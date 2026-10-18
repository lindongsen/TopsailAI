Feature: Control a pending first decoded LLM response
  A session operator can abandon a waiting turn or retry its request
  without replaying tools or silently changing request retry policy

  Scenario Outline: Route an exact command over a local socket during an HTTP wait
    Given a controlled mock LLM request waiting in "<phase>" with timeout "<timeout>"
    When the operator sends "<operation>" through the control socket
    Then the command is queued before coordinator acceptance
    And the request has the "<outcome>" outcome without stale output

    Examples:
      | phase      | timeout | operation      | outcome     |
      | headers    | 0       | force_retry    | fresh retry |
      | first_item | 1       | force_retry    | fresh retry |
      | headers    | -1      | hard_interrupt | abandoned   |
      | first_item | 0.01    | hard_interrupt | abandoned   |

  Scenario Outline: Control the current request without target discovery
    Given a controlled mock LLM request waiting in "<phase>" with timeout "0"
    When the operator sends action-only "<operation>" through the control socket
    Then the command is queued before coordinator acceptance
    And the request has the "<outcome>" outcome without stale output

    Examples:
      | phase      | operation      | outcome     |
      | headers    | force_retry    | fresh retry |
      | first_item | force_retry    | fresh retry |
      | headers    | hard_interrupt | abandoned   |
      | first_item | hard_interrupt | abandoned   |

  Scenario Outline: Retransmit a stable current-request command after the target changes
    Given a controlled mock LLM request waiting in "<phase>" with timeout "0"
    When the operator sends action-only "force_retry" with stable ID "lost-response-retry" through the control socket
    Then the command is queued before coordinator acceptance
    And the request has the "fresh retry" outcome without stale output

    Examples:
      | phase      |
      | headers    |
      | first_item |

  Scenario Outline: Recover a lost socket receipt without retrying the next request
    Given a controlled mock LLM request waiting in "<phase>" with timeout "0"
    When the first stable-ID command response is lost before socket delivery
    Then the command is queued before coordinator acceptance
    And the request has the "fresh retry" outcome without stale output

    Examples:
      | phase      |
      | headers    |
      | first_item |
