Feature: bidirectional channel convergence

  Scenario: both sides dial and the cluster converges on one working link
    Given a real cluster in the bidirectional channel direction
    Then the inventory is read through the real HTTP boundary
    And the inventory contains at least one session from the real provider
    And the endpoint is reported online through the real HTTP boundary

  Scenario: a command round-trips over the converged link exactly once
    Given a real cluster in the bidirectional channel direction
    When a send command is submitted for the fixture session
    Then the command reaches a terminal state
    And the provider was invoked exactly once

  Scenario: one shared certificate still establishes the link
    Given a real cluster in the bidirectional channel direction with one shared certificate
    Then the inventory is read through the real HTTP boundary
    And the inventory contains at least one session from the real provider
    And the endpoint is reported online through the real HTTP boundary
