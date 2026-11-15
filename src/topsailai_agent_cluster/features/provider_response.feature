Feature: provider raw return display

  A session scope command result has two parts: this service's own durable
  receipt and the provider's own raw return document. The provider document is
  opaque evidence, so it is never reinterpreted as a provider success claim. It
  is rendered as readable text for the operator, while storage and the --json
  envelope keep the provider's original bytes.

  Scenario: session scope send shows the service receipt and the provider raw return
    Given a real cluster with a healthy provider for the interactive REPL
    When a session scope send is driven through the interactive REPL
    Then the interactive output shows the service receipt section
    And the interactive output shows the provider raw return section
    And the interactive output renders the provider document as readable text
    And the service receipt section appears before the provider raw return section

  Scenario: provider failure shows the provider diagnostic
    Given a real cluster whose provider fails execution
    When a session scope send is driven through the interactive REPL
    Then the interactive output shows the provider raw return section
    And the interactive output shows the provider diagnostic

  Scenario: standalone btw shows the provider raw return as readable text
    Given a real cluster with a healthy provider for the interactive REPL
    When a session scope btw is driven through the standalone command
    Then the standalone output shows the service receipt section
    And the standalone output shows the provider raw return section
    And the standalone output renders the provider document as readable text
    And the service receipt section appears before the provider raw return section

  Scenario: standalone btw keeps the machine envelope under --json
    Given a real cluster with a healthy provider for the interactive REPL
    When a session scope btw is driven through the standalone command with --json
    Then the standalone output is one parseable JSON document
    And the JSON document carries the provider document as a string
