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
