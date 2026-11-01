Feature: inventory persistence
  Scenario: a valid complete inventory is returned through the real HTTP boundary
    Given an isolated Agent Cluster server
    When endpoint "endpoint-1" submits a complete inventory with revision 1
    Then the inventory request succeeds
    And the latest inventory for "endpoint-1" contains adapter "adapter-1"

  Scenario: malformed inventory does not become an empty list
    Given an isolated Agent Cluster server
    When endpoint "endpoint-1" submits an invalid inventory
    Then the inventory request is rejected

  Scenario: a successful empty inventory clears the source
    Given an isolated Agent Cluster server
    When endpoint "endpoint-1" submits an empty complete inventory with revision 1
    Then the inventory request succeeds
    And the latest inventory for "endpoint-1" contains zero sessions

  Scenario: real cluster reports inventory through the real boundary
    Given a real cluster with a healthy provider
    When the inventory is read through the real HTTP boundary
    Then the inventory contains at least one session from the real provider
    And the session carries a non-empty generation

  Scenario: one failed source does not affect another source
    Given a real cluster with two adapters where adapter-a succeeds and adapter-b fails
    When the real Endpoint publishes the isolated adapter inventory
    Then adapter-a retains its sessions while adapter-b is marked failed

  Scenario: failed source retains its last successful data as stale
    Given a real cluster whose provider fails after the first discovery
    When the real Endpoint refreshes inventory after provider failure
    Then the real source retains its sessions and is automatically marked stale

  Scenario: first source failure is unknown rather than an empty list
    Given a real cluster whose provider fails before the first discovery
    When the real Endpoint publishes the failed first inventory
    Then the real source is automatically unknown rather than a successful empty list

  Scenario: truncated inventory is marked incomplete
    Given an isolated Agent Cluster server
    When endpoint "endpoint-1" submits a truncated partial report
    Then the report is marked incomplete rather than successful
