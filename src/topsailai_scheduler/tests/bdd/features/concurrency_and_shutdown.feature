Feature: Concurrency and shutdown
  As an operator running the scheduler
  I want the concurrency limit and the shutdown drain to behave predictably
  So that a burst of tasks cannot exhaust the machine and a restart cannot
  abandon work silently

  Both knobs are daemon-wide and are read once at startup, so a scenario that
  exercises one restarts the daemon with it. Neither can be expressed in a task
  file, which is why they are not part of the configuration feature.

  The concurrency limit is a slot pool, not a rejection: a launch waits for a
  slot instead of failing. Waiting is observable as a duration, and the second
  run reaching the provider afterwards is what proves the wait ended in a run
  rather than in a silent drop.


  Scenario: A launch waits for a concurrency slot
    Given a scheduler that allows one run at a time
    And two tasks that each sleep for a while
    When I launch the first task without waiting
    And I launch the second task and time it
    Then the second launch waited for the first run
    And the provider received a request for each task

  Scenario: Shutdown waits for a running task
    Given a scheduler with a generous shutdown grace
    And a task that sleeps for a while
    When I launch that task without waiting
    And I stop the scheduler gracefully
    Then the shutdown waited for the run
    And the scheduler exited cleanly

  Scenario: Shutdown ends a run that outlives the grace period
    Given a scheduler with a short shutdown grace
    And a task that sleeps far longer than the grace period
    When I launch that task without waiting
    And I stop the scheduler gracefully
    Then the grace period is reported as expired
    And the run is recorded as canceled
