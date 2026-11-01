Feature: real command boundary
  Scenario: real command reaches the provider exactly once
    Given a real cluster with a healthy provider
    When a send command is submitted for the fixture session
    Then the command reaches a terminal state
    And the provider was invoked exactly once


  Scenario: stop request reports signal sent without claiming exit
    Given a running cluster with one endpoint
    And a running session with a known generation
    When I submit a stop command for that session
    Then the receipt reports delivery state signal_sent
    And the receipt reports exit confirmed false
    And the command status is not finished
