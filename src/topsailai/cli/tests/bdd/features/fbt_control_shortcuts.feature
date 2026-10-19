Feature: Current-request control shortcuts
  The Human runtime shortcut criterion requires exact FBT operations without
  changing legacy interrupts or selecting another process.

  Scenario Outline: Send an exact current-request shortcut
    Given a local control socket that returns "ok"
    When I enter "/control.fbt.<shortcut>" with a watched PID
    Then one request carries "llm_control" and operation "<operation>"
    And the control response contains "accepted"

    Examples:
      | shortcut        | operation      |
      | force_retry     | force_retry    |

  Scenario: Surface an idle backend rejection without retry or fallback
    Given a local control socket that returns "error"
    When I enter "/control.fbt.force_retry" with a watched PID
    Then one request carries "llm_control" and operation "force_retry"
    And the control response contains "no_active_target"

  Scenario: Do not send without a watched PID
    Given a local control socket that returns "ok"
    When I enter a first-byte shortcut without a watched PID
    Then no control request is sent
    And the control response contains "Could not resolve the watched session PID"

  Scenario: Preserve the legacy interrupt action
    Given a local control socket that returns "ok"
    When I enter "/control.hard_interrupt" with a watched PID
    Then one request carries "hard_interrupt" and operation "none"
    And the control response contains "accepted"

  Scenario: Reject the removed first-byte interrupt shortcut
    Given a local control socket that returns "ok"
    When I enter "/control.fbt.hard_interrupt" with a watched PID
    Then no control request is sent
