Feature: Configuration propagation
  As an operator running the scheduler
  I want every configuration detail to reach the provider unchanged
  So that a task's declared intent is what actually runs

  The mock provider records the request document it received verbatim, so each
  assertion is made against what the scheduler actually sent rather than against
  a log line that merely claims it did. A field the provider ignores is still
  verifiable, which is what makes this a real check rather than a smoke test.


  Scenario: A task that names every optional field sends them all
    Given a task that names its workspace timeout and environment
    When I launch that task and wait for it
    Then the provider received the workspace the task named
    And the provider received the timeout the task named
    And the provider received the environment the task named
    And the provider received the command the task named

  Scenario: A task that names no optional field receives the defaults
    Given a task that names no optional field
    When I launch that task and wait for it
    Then the provider received the default workspace
    And the provider received the default timeout
    And the provider received no environment

  Scenario: Every placeholder is expanded
    Given a task whose arguments carry every placeholder
    When I launch that task and wait for it
    Then the provider received every placeholder expanded

  Scenario: A placeholder embedded in a longer argument is expanded
    Given a task whose argument embeds a placeholder in a longer string
    When I launch that task and wait for it
    Then the embedded placeholder is expanded in place

  Scenario: The protocol version is the one the provider speaks
    Given a task that prints a line
    When I launch that task and wait for it
    Then the provider received the current protocol version

  Scenario: A task that names its own provider uses it
    Given a task that names the mock provider explicitly
    When I launch that task and wait for it
    Then the provider received the request

  Scenario: A task that names an unknown provider is refused
    Given a task that names an unknown provider
    When I launch that task
    Then the launch is refused because the provider is unknown
    And that task is never launched

  Scenario: A task whose provider is missing is rejected at schedule time
    Given a task that names an unknown provider
    Then that task is reported as invalid
    And that task has no next run

  Scenario: A task is scheduled once its provider exists
    Given a task whose provider appears later
    Then that task is reported as invalid
    When the provider executable is installed
    Then that task is reported as idle
