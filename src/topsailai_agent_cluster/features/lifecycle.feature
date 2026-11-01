Feature: launch lifecycle

  Scenario: start with mismatched profile revision is rejected
    Given a running cluster with one endpoint
    When I submit a start command with an unknown profile revision
    Then the command is rejected
    And the command exposes an error code
