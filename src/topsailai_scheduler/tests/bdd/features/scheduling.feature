Feature: Cron scheduling
  As an operator running the scheduler
  I want a task to fire on its own schedule
  So that the scheduler does its job without anyone calling launch

  Every other feature drives a run through the CLI, which proves the launch
  path but says nothing about the cron. A scheduler that never fires on its own
  would still pass those scenarios. Here nothing calls launch: a request
  reaching the provider is only possible because the cron fired.

  The cron instance runs with seconds enabled, so a six-field expression is
  accepted directly and a familiar five-field expression is prefixed with a
  zero second field rather than rejected.


  Scenario: A task fires on its own schedule
    Given a task scheduled every two seconds
    When I wait for the schedule to fire
    Then the provider received at least one request for that task
    And the task is logged as scheduled

  Scenario: A five-field schedule is accepted
    Given a task with a five-field schedule
    Then that task is scheduled with a next run

  Scenario: A schedule that cannot be parsed is reported and never fires
    Given a task whose schedule cannot be parsed
    When the scheduler rescans the task tree
    Then that task is reported as idle with no next run
    And the schedule failure is logged
    And that task is never launched

  Scenario: A changed schedule takes effect without a restart
    Given a task scheduled every two seconds
    When I wait for the schedule to fire
    And I change its schedule to every second
    Then the task is rescheduled without a restart
    And the provider receives more requests than before
