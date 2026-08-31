Feature: Tag and move topsailai-data objects

  Scenario: Add remove and idempotently add an object tag
    Given an isolated topsailai-data store
    When I create object "tag-object" from fixture "markdown/valid.md" with description "Tag object" and tags "base"
    Then the command succeeds
    When I run topsailai-data with arguments:
      | tag |
      | add |
      | tag-object |
      | added |
    Then the command succeeds
    When I run topsailai-data with arguments:
      | tag |
      | add |
      | tag-object |
      | added |
    Then the command succeeds
    And the JSON list contains object "tag-object" with tags "base,added"
    When I run topsailai-data with arguments:
      | tag |
      | remove |
      | tag-object |
      | added |
    Then the command succeeds
    And the JSON list contains object "tag-object" with tags "base"

  Scenario: Recursive classify tags are inherited and deduplicated
    Given an isolated topsailai-data store
    When I create object "inherited-tags" from fixture "markdown/valid.md" with description "Inherited tags" and classify "projects/team/demo"
    Then the command succeeds
    When I add classify tags "root-tag,shared" to "inherited-tags" at level "projects"
    Then the command succeeds
    When I add classify tags "team-tag,shared" to "inherited-tags" at level "projects/team"
    Then the command succeeds
    When I add classify tags "demo-tag,shared" to "inherited-tags" at level "projects/team/demo"
    Then the command succeeds
    And the JSON list contains object "inherited-tags" with tags "root-tag,shared,team-tag,demo-tag"
    When I run topsailai-data with arguments:
      | tag |
      | remove |
      | inherited-tags |
      | root-tag |
    Then the command fails
    And the JSON list contains object "inherited-tags" with tags "root-tag,shared,team-tag,demo-tag"

  Scenario: Move preserves identity timestamps markdown and extra actual data
    Given an isolated topsailai-data store
    When I create object "movable-object" from fixture "markdown/valid.md" with description "Movable object" and classify "before/source"
    Then the command succeeds
    And the JSON list contains object "movable-object" with path classify "before/source"
    When I run topsailai-data with arguments:
      | put |
      | movable-object |
      | extra.txt |
      | --from |
      | tests/bdd/fixtures/markdown/extra.txt |
    Then the command succeeds
    When I record public metadata for "movable-object"
    Then the command succeeds
    When I run topsailai-data with arguments:
      | move |
      | movable-object |
      | after |
      | destination |
    Then the command succeeds
    And the JSON list contains object "movable-object" with path classify "after/destination"
    And the JSON list contains object "movable-object" with data reference matching path classify "after/destination"
    And the object "movable-object" retains recorded identity and creation metadata
    When I run topsailai-data with arguments:
      | get |
      | movable-object |
      | movable-object.md |
    Then the command succeeds
    And stdout contains "Smoke test content"
    When I run topsailai-data with arguments:
      | get |
      | movable-object |
      | extra.txt |
    Then the command succeeds
    And stdout contains "Extra user actual data"

  Scenario Outline: Tags and moves reject non-active or unknown objects
    Given an isolated topsailai-data store
    When I create object "<name>" from fixture "markdown/valid.md" with description "State object"
    Then the command succeeds
    When I delete object "<name>" <delete-count> times
    Then the command succeeds
    When I run topsailai-data with arguments:
      | tag |
      | add |
      | <name> |
      | rejected |
    Then the command fails
    When I run topsailai-data with arguments:
      | move |
      | <name> |
      | rejected |
    Then the command fails

    Examples:
      | name | delete-count |
      | deleted-tag-move | once |
      | ceased-tag-move | twice |

  Scenario: Tags and moves reject an unknown object
    Given an isolated topsailai-data store
    When I run topsailai-data with arguments:
      | tag |
      | add |
      | unknown-tag-move |
      | rejected |
    Then the command fails
    When I run topsailai-data with arguments:
      | move |
      | unknown-tag-move |
      | rejected |
    Then the command fails
