Feature: command cancellation

  Scenario: undispatched command can be cancelled without side effect
    Given an isolated Agent Cluster server
    When a command "bdd-cancel-before" is admitted
    And the command "bdd-cancel-before" is cancelled before dispatch
    Then the command cancellation succeeds
    And the command "bdd-cancel-before" is cancelled before execution

  Scenario: dispatched command is too late to cancel
    Given an isolated Agent Cluster server
    When a command "bdd-cancel-late" is admitted and dispatched
    And the command "bdd-cancel-late" is cancelled after dispatch
    Then cancellation is too late

  Scenario: cancellation does not invoke the provider
    Given an isolated Agent Cluster server
    When a command "bdd-cancel-provider" is admitted
    And the command "bdd-cancel-provider" is cancelled before dispatch
    Then the provider invocation count is zero

  Scenario: cancellation and dispatch have one atomic winner
    Given an isolated Agent Cluster server
    When cancellation and dispatch race for command "bdd-cancel-race"
    Then exactly one cancellation boundary wins

  Scenario: cancellation does not invoke the provider through the real boundary
    Given a real cluster is started with a 2000ms dispatch delay
    When a real command is admitted and cancellation is requested immediately
    Then the real command is cancelled before provider execution

  Scenario: cancellation and dispatch have one atomic winner through the real boundary
    Given a real cluster is started with a 500ms dispatch delay
    When a real command send and cancellation race with a 500ms dispatch delay
    Then the real cancellation race has one winner and at most one provider invocation
