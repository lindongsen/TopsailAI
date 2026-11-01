Feature: capability boundaries

  Scenario: unsupported capability is explicit
    Given an isolated Agent Cluster server
    When an unsupported capability is requested
    Then the response is unsupported

  Scenario: unsupported stop does not use interrupt
    Given an isolated Agent Cluster server
    When stop is requested from an adapter without stop capability
    Then the response is unsupported
    And no interrupt operation is attempted

  Scenario: platform capability insufficiency rejects stop
    Given an adapter with missing pidfd platform capability
    When stop is requested from that adapter
    Then the adapter response is unsupported

  Scenario: stop requires a generation
    Given an adapter with stop platform capability
    When stop is requested without a generation
    Then the adapter response reports generation required
