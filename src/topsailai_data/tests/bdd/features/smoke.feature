Feature: Core topsailai-data CLI smoke flow
  @smoke @core
  Scenario: Create list and show an object
    Given an isolated topsailai-data store
    When I create object "smoke-note" from fixture "markdown/valid.md"
    Then the command succeeds
    When I run topsailai-data with arguments:
      | list |
      | --format |
      | json |
    Then the command succeeds
    And stdout contains "smoke-note"
    When I run topsailai-data with arguments:
      | show |
      | smoke-note |
    Then the command succeeds
    And stdout contains "Status:        active"
    And stdout contains "Smoke test content"
