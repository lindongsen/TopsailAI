Feature: Simplified configured Hook runtime
  As a host application
  I want to register executable Hook scripts by exact name
  So that ordered plans execute and are cleaned up without caller-managed resources

  Scenario: Ordered scripts execute through the public Runtime boundary
    Given a simplified Hook runtime configured with ordered scripts
    When the configured Hook is executed through its exact public name
    Then the configured Hook execution succeeds in name order
    And closing the simplified Hook runtime removes its captured artifacts

  Scenario: A recursive folder executes in deterministic relative-path order
    Given a simplified Hook runtime configured from a recursive folder
    When the configured Hook is executed through its exact public name
    Then the configured Hook execution succeeds in folder order
    And closing the simplified Hook runtime removes its captured artifacts

  Scenario: Configured execution requires the exact registered Hook name
    Given a simplified Hook runtime configured for exact-name selection
    When the configured Hook is executed through a different valid name
    Then the configured Hook execution is rejected as unknown
    And closing the simplified Hook runtime removes its captured artifacts

  Scenario: Atomic replacement preserves the last successful plan
    Given a simplified Hook runtime with an atomically replaced plan
    When a later invalid replacement is rejected
    And the configured Hook is executed through its exact public name
    Then the replacement plan remains active
    And closing the simplified Hook runtime removes its captured artifacts
