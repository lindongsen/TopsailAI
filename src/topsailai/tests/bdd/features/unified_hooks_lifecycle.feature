Feature: Standalone Unified Hooks bounded lifecycle
  As a host application
  I want hook deadlines and cancellation to remain bounded
  So that optional hook work cannot take over the host lifecycle

  Scenario: A timed-out hook prevents later hook startup
    Given a standalone Unified Hooks lifecycle runtime for timeout
    When the host dispatches one event to a deterministically stalled worker
    And the lifecycle runtime is closed after settlement
    Then the timeout report preserves the host main flow
    And only the timed-out worker started
    And the lifecycle public close report and observed worker are settled

  Scenario: Host cancellation propagates while owned work remains until cooperative release
    Given a standalone Unified Hooks lifecycle runtime for cancellation
    When the host cancels public asynchronous dispatch after the worker starts
    And the lifecycle runtime is closed after settlement
    Then host cancellation propagates boundedly before cooperative worker release
    And only the cancelled dispatch worker started
    And the lifecycle public close report and observed worker are settled

  Scenario: Bounded close is idempotent and rejects later admission
    Given a standalone Unified Hooks lifecycle runtime for bounded-close
    When the host closes the runtime with a finite deadline during real worker execution
    Then bounded close returns with pending host work diagnostics
    And repeated close is idempotent and later dispatch is rejected
    And the original host flow settles without starting a successor
    And the lifecycle public close report and observed worker are settled
