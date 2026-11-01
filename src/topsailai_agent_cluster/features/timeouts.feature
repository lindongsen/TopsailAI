Feature: command timeouts
  Scenario: expired command is not applied
    Given an isolated Agent Cluster server
    When an expired command "bdd-expired" is submitted
    Then the command effect is not applied

  Scenario: caller wait timeout does not change execution fact
    Given an isolated Agent Cluster server
    When a command "bdd-wait-timeout" is submitted with a caller wait timeout
    Then the command remains queryable

  Scenario: late query preserves the durable command result
    Given an isolated Agent Cluster server
    When a command "bdd-late-result" is submitted
    Then a later query returns the same command

  Scenario: dispatched command remains awaiting confirmation before receipt
    Given a real cluster is started with a 3000ms receipt delay
    When a real command is submitted for the fixture session
    And the real command is observed before its receipt arrives
    Then the early command status is awaiting confirmation rather than not applied

  Scenario: invocation timeout preserves unknown effect certainty
    Given a real cluster is started with invocation crash enabled
    When a real command is submitted for the fixture session
    Then the real command eventually has unknown effect certainty
    And the provider invocation count is one

  Scenario: late reliable receipt does not reexecute the provider
    Given a real cluster is started with a 2000ms receipt delay
    When a real command is submitted for the fixture session
    And the delayed real command is first non-terminal
    Then the delayed real command eventually reaches a terminal state
    And the provider invocation count is one

  Scenario: caller wait timeout preserves the later real execution result
    Given a real cluster is started with a 2000ms receipt delay
    When a real command is submitted and polled with a 100ms caller timeout
    Then a later real query returns the durable execution result
    And the provider invocation count is one

  Scenario: not applied command is not reported as finished
    Given a running cluster with one endpoint
    And a command that is rejected before invocation
    When the receipt reports not applied
    Then the command status is not finished
    And the command exposes an error code

  Scenario: tui waits for terminal state within budget
    Given a running cluster with one endpoint
    When I submit a command with a sufficient wait budget
    Then the tui reports a terminal state
