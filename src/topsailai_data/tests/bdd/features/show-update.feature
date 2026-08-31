Feature: Show and update topsailai-data objects

  Scenario: Show an active object with markdown and visible user files
    Given an isolated topsailai-data store
    When I create object "shown-note" from fixture "markdown/valid.md" with description "Shown description"
    Then the command succeeds
    When I run topsailai-data with arguments:
      | put |
      | shown-note |
      | extra.txt |
      | --from |
      | tests/bdd/fixtures/markdown/extra.txt |
    Then the command succeeds
    When I run topsailai-data with arguments:
      | tag |
      | add |
      | shown-note |
      | visible-tag |
    Then the command succeeds
    When I run topsailai-data with arguments:
      | show |
      | shown-note |
    Then the command succeeds
    And stdout contains "ID:            shown-note"
    And stdout contains "Name:          shown-note"
    And stdout contains "Description:   Shown description"
    And stdout contains "Status:        active"
    And stdout contains "# Smoke test content"
    And stdout contains "shown-note.md"
    And stdout contains "extra.txt"
    And stdout does not contain "shown-note.tags"
    And stdout does not contain ".stat.json"
    And stdout does not contain ".lock"
    And stdout does not contain "metadata.json"

  Scenario: Update and clear an active object description
    Given an isolated topsailai-data store
    When I create object "update-note" from fixture "markdown/valid.md" with description "Initial description"
    Then the command succeeds
    When I run topsailai-data with arguments:
      | update |
      | update-note |
      | --description |
      | Updated description |
    Then the command succeeds
    And the JSON list contains object "update-note" with description "Updated description" and status "active"
    And the YAML list contains object "update-note" with description "Updated description" and status "active"
    When I run topsailai-data with arguments:
      | update |
      | update-note |
      | --description= |
    Then the command succeeds
    And the JSON list contains object "update-note" with description "" and status "active"

  Scenario: Update unknown object fails
    Given an isolated topsailai-data store
    When I run topsailai-data with arguments:
      | update |
      | unknown-note |
      | --description |
      | No object |
    Then the command fails

  Scenario Outline: Update deleted or ceased object fails and preserves metadata
    Given an isolated topsailai-data store
    When I create object "<name>" from fixture "markdown/valid.md" with description "Original description"
    Then the command succeeds
    When I delete object "<name>" <delete-count> times
    Then the command succeeds
    When I run topsailai-data with arguments:
      | update |
      | <name> |
      | --description |
      | Replacement description |
    Then the command fails
    And the JSON list including deleted objects contains object "<name>" with description "Original description" and status "<status>"

    Examples:
      | name | delete-count | status |
      | deleted-note | once | deleted |
      | ceased-note | twice | ceased |
