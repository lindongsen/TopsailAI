Feature: command capability routing

  Scenario: control command reaches provider through declared capability
    Given a running cluster with one endpoint
    And a running session with a known generation
    When I submit a control command for that session
    Then the command is not rejected as unsupported
