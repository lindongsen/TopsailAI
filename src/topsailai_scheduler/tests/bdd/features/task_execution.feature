Feature: Task execution and lifecycle
  As an operator running the scheduler
  I want a run to start, be observed and end predictably
  So that I can trust the schedule without watching it

  The scheduler is a process supervisor. It starts a run, observes whether that
  run is still alive, and stops it when asked. It never decides whether the work
  succeeded: that judgement belongs to the task's Markdown content. The exit code
  is reported as a lifecycle fact, never as a verdict.


  Scenario: A task runs when it is launched
    Given a task that prints a line
    When I launch that task and wait for it
    Then the launch reports exit code 0
    And the run's output is captured

  Scenario: A run that exits non-zero is reported as a fact
    Given a task that exits with status 3
    When I launch that task and wait for it
    Then the launch reports exit code 3
    And the launch exits non-zero

  Scenario: A task that outlives its timeout is ended
    Given a task that sleeps far longer than its timeout
    When I launch that task and wait for it
    Then the launch reports a timeout
    And the timeout is logged

  Scenario: A running task can be stopped
    Given a task that sleeps longer than the test
    When I launch that task without waiting
    And I stop that task
    Then the stop is reported as supervised
    And the run ends
    And the run is recorded as stopped

  Scenario: Stopping a task that is not running is refused
    Given a task that prints a line
    When I stop that task
    Then the stop is refused as not running

  Scenario: A task's own environment variables reach the run
    Given a task that reads an environment variable it defines
    When I launch that task and wait for it
    Then the run sees the value the task defined

  Scenario: A run executes in the workspace the task named
    Given a task that records its working directory
    When I launch that task and wait for it
    Then the run recorded the workspace the task named
