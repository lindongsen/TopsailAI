Feature: capability boundaries

  Scenario: unsupported capability is explicit
    Given an isolated Agent Cluster server
    When an unsupported capability is requested
    Then the response is unsupported

