Feature: Control contract
  As an operator driving the scheduler from a script
  I want the CLI to report state and reject a wrong command line distinctly
  So that a script can tell "I called it wrong" from "the task failed"

  The CLI is one transport over the control contract. It reports the same
  snapshot the daemon produces, and it separates a usage error (exit 2) from a
  failed operation (exit 1), so a caller never has to parse message text to know
  which happened.


  Scenario: The status snapshot lists a discovered task
    Given a task that prints a line
    When I ask for the status as JSON
    Then the snapshot names the task
    And the snapshot reports the tasks root
    And the snapshot reports the task as idle

  Scenario: The status table names the task
    Given a task that prints a line
    When I ask for the status as a table
    Then the table names the task

  Scenario: A launch reports the run it started
    Given a task that prints a line
    When I launch that task without waiting
    Then the launch reports the task id and a pid
    And I stop that task

  Scenario: A launch of an unknown task is refused
    When I launch a task that does not exist
    Then the launch is refused as not found

  Scenario: A launch with no task id is a usage error
    When I launch with no task id
    Then the command line is rejected as a usage error

  Scenario: An unknown subcommand is a usage error
    When I run an unknown subcommand
    Then the command line is rejected as a usage error

  Scenario: The help text names every subcommand
    When I ask for help
    Then the help text names every subcommand

  Scenario: A launch result can be read as JSON
    Given a task that prints a line
    When I launch that task as JSON and wait for it
    Then the JSON result names the task and its exit code
