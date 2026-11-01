Feature: latest-state notifications
  Scenario: a committed inventory update emits an invalidation event
    Given an isolated Agent Cluster server with notifications
    When endpoint "endpoint-1" submits a complete inventory with revision 1
    Then an inventory changed event for "endpoint-1" is observable

  Scenario: the manifest exposes the latest committed revision
    Given an isolated Agent Cluster server with notifications
    When endpoint "endpoint-1" submits a complete inventory with revision 1
    Then the manifest reports revision 1 for "endpoint-1"
