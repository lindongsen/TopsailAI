Feature: Restart reconciliation
  As an operator running the scheduler
  I want a restart to notice a run the previous supervisor left behind
  So that the same task is never worked on twice

  A run is a separate process that outlives the scheduler. After a restart the
  lock is free while the run may still be working, so the lock alone cannot
  answer "is this task busy". The record the previous supervisor wrote into the
  lock file is the only thing that names the run, and it is reconciled before a
  new run starts.

  The record is advisory, never authoritative: the kernel lock remains the
  authority for "a scheduler is supervising this task right now".


  Scenario: A run left in flight by a killed supervisor is not started twice
    Given a task that outlives a killed supervisor
    When I launch that task without waiting
    And I kill the scheduler
    And I restart the scheduler
    And I launch that task again
    Then the second launch is skipped as already running
    And the provider received exactly one request for that task
    And the skip is logged as a reconciliation

  Scenario: The record survives the supervisor that wrote it
    Given a task that outlives a killed supervisor
    When I launch that task without waiting
    And I kill the scheduler
    Then the lock record still names the run

  Scenario: A recorded run that already finished no longer blocks the task
    Given a task that finishes soon after its supervisor dies
    When I launch that task without waiting
    And I kill the scheduler
    And the recorded run finishes on its own
    And I restart the scheduler
    And I launch that task again
    Then the launch starts a new run
    And the provider received two requests for that task

  Scenario: A stop is forwarded to a run left by a killed supervisor
    Given a task that outlives a killed supervisor
    When I launch that task without waiting
    And I kill the scheduler
    And I restart the scheduler
    And I stop that task
    Then the stop is reported as best effort
    And the recorded run ends

  Scenario: A stop is refused once the supervised run has ended
    Given a task that prints a line
    When I launch that task and wait for it
    And I stop that task
    Then the stop is refused as not running
