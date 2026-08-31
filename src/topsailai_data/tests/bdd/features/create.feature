Feature: Create topsailai-data objects

  Scenario: Create an object with explicit description tags and classify path
    Given an isolated topsailai-data store
    When I create object "created-note" from fixture "markdown/valid.md" with description "Explicit description", tags "alpha,beta", and classify "projects/demo"
    Then the command succeeds
    And the JSON list contains object "created-note" with description "Explicit description" and status "active"
    And the JSON list contains object "created-note" with tags "alpha,beta"
    And the YAML list contains object "created-note" with description "Explicit description" and status "active"
    And the object "created-note" path has classify "projects/demo"
  Scenario: Extract description from frontmatter
    Given an isolated topsailai-data store
    When I create object "frontmatter-note" from fixture "markdown/frontmatter.md"
    Then the command succeeds
    And the JSON list contains object "frontmatter-note" with description "Frontmatter description" and status "active"

  Scenario: Explicit description overrides frontmatter
    Given an isolated topsailai-data store
    When I create object "override-note" from fixture "markdown/frontmatter.md" with description "Flag description"
    Then the command succeeds
    And the JSON list contains object "override-note" with description "Flag description" and status "active"

  Scenario: Create an object from stdin with complete arguments
    Given an isolated topsailai-data store
    When I create object "stdin-note" from stdin with description "Stdin description" and content "stdin markdown content"
    Then the command succeeds
    And the JSON list contains object "stdin-note" with description "Stdin description" and status "active"

  Scenario Outline: Reject invalid description frontmatter
    Given an isolated topsailai-data store
    When I create object "invalid-description" from fixture "<fixture>"
    Then the command fails with "description"

    Examples:
      | fixture |
      | markdown/malformed-frontmatter.md |
      | markdown/missing-description.md |
      | markdown/non-string-description.md |

  Scenario: Reject an empty create input
    Given an isolated topsailai-data store
    When I run topsailai-data with arguments:
      | create |
      | empty-note |
    Then the command fails with "markdown"

  Scenario: Reject duplicate active object without changing the original
    Given an isolated topsailai-data store
    When I create object "duplicate-note" from fixture "markdown/valid.md" with description "Original description"
    Then the command succeeds
    When I create object "duplicate-note" from fixture "markdown/alternate.md" with description "Replacement description"
    Then the command fails
    And the JSON list contains object "duplicate-note" with description "Original description" and status "active"
