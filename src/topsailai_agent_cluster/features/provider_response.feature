Feature: provider raw return display

  A session scope command result has two parts: this service's own durable
  receipt and the provider's own raw return document. The provider document is
  opaque evidence, so it is displayed verbatim and never reinterpreted as a
  provider success claim.

  Scenario: session scope send shows the service receipt and the provider raw return
    Given a real cluster with a healthy provider for the interactive REPL
    When a session scope send is driven through the interactive REPL
    Then the interactive output shows the service receipt section
    And the interactive output shows the provider raw return section
    And the interactive output carries the provider document verbatim
    And the service receipt section appears before the provider raw return section

  Scenario: provider failure shows the provider diagnostic
    Given a real cluster whose provider fails execution
    When a session scope send is driven through the interactive REPL
    Then the interactive output shows the provider raw return section
    And the interactive output shows the provider diagnostic
