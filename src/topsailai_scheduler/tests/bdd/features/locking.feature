Feature: Locking and concurrency
  As an operator running the scheduler
  I want one task to have at most one run in flight
  So that a slow task cannot be duplicated by the next tick

  The lock is a kernel advisory lock on the task's own .lock file, held for the
  whole supervision rather than only for the start call. A lock bound to the
  start call would be released while the run was still working, which is exactly
  the duplication this feature prevents.


  Scenario: A task that is already running is not started twice
    Given a task that sleeps longer than the test
    When I launch that task without waiting
    And I launch that task again without waiting
    Then the second launch is skipped as already running
    And the provider received exactly one request for that task
    And I stop that task

  Scenario: The lock is held for the whole run
    Given a task that sleeps longer than the test
    When I launch that task without waiting
    Then the lock file carries a record naming the run
    And the record names the provider that owns the run
    And the record names the supervisor that wrote it
    And I stop that task

  Scenario: The lock record is cleared once the run is confirmed over
    Given a task that prints a line
    When I launch that task and wait for it
    Then the lock record is empty

  Scenario: A task that is not running can be launched again
    Given a task that prints a line
    When I launch that task and wait for it
    And I launch that task and wait for it again
    Then the provider received two requests for that task
