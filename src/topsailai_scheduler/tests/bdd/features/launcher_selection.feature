Feature: Launcher selection
  As an operator running the scheduler
  I want the launcher to decide what the provider is asked to run
  So that a task can either name its own command or leave the invocation to the
  provider

  The launcher and the provider answer different questions. The launcher
  describes the run; the provider performs it. A task that names no launcher
  gets the agent launcher, which supplies only the facts the scheduler owns and
  leaves the command empty so the provider chooses the invocation itself.

  This is the difference between "run this command" and "run this task". A
  provider that wraps one specific tool needs the second form, and it can only
  recognise it if the command is genuinely absent rather than defaulted to
  something plausible.


  Scenario: The agent launcher leaves the invocation to the provider
    Given a task that names no launcher
    When I launch that task and wait for it
    Then the provider received no command
    And the provider received no arguments
    And the provider received the task content path
    And the provider received the default timeout

  Scenario: A task that names an unknown launcher is refused
    Given a task that names an unknown launcher
    When I launch that task
    Then the launch is refused because the launcher is unknown
    And that task is never launched

  Scenario: The command launcher sends the command the task named
    Given a task that names the command launcher
    When I launch that task and wait for it
    Then the provider received the command the task named
    And the provider received the arguments the task named
