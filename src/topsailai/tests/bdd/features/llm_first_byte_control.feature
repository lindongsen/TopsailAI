Feature: Execute staged control during a first-byte wait
  A session operator uses generic interruption or retries the current request
  without replaying tools or introducing a separate control wait

  Scenario Outline: Consume a flag from the existing HTTP wait Hook
    Given a controlled mock LLM request waiting in "<phase>" with timeout "<timeout>"
    When the operator stages "<operation>" through the control socket
    Then the wait executes the command without stale output

    Examples:
      | phase      | timeout | operation      |
      | headers    | 0       | force_retry    |
      | first_item | 1       | force_retry    |
      | headers    | -1      | hard_interrupt |
      | first_item | 0.01    | hard_interrupt |
