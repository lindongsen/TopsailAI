Feature: Store layout and metadata addressing

  The store container holds two sibling trees: object/ for payloads and meta/
  for identity-addressed metadata. A layout marker records the format so an
  unmarked non-empty directory is never mistaken for a fresh store.

  Scenario: A fresh store initializes the layout marker and both trees
    Given an isolated topsailai-data store
    When I run topsailai-data with arguments:
      | list |
      | --format |
      | json |
    Then the command succeeds
    And the store layout is initialized

  Scenario: An unmarked non-empty store root is rejected instead of migrated
    Given an isolated topsailai-data store
    And a store root containing an unrelated file "stray.txt"
    When I run topsailai-data with arguments:
      | list |
      | --format |
      | json |
    Then the command fails with "unmarked nonempty store"

  Scenario: Metadata lives under a hashed directory with a separate tags file
    Given an isolated topsailai-data store
    When I create object "layout-note" from fixture "markdown/valid.md" with description "Layout note" and tags "alpha"
    Then the command succeeds
    And object "layout-note" metadata is stored under a hashed directory with a separate tags file
    And the JSON list contains object "layout-note" with tags "alpha"

  Scenario: The data reference is relative to the object tree
    Given an isolated topsailai-data store
    When I create object "ref-note" from fixture "markdown/valid.md" with description "Reference note" and classify "projects/demo"
    Then the command succeeds
    And the data reference of object "ref-note" is relative to the object tree

  Scenario: A classify tag file is not inherited by an object
    Given an isolated topsailai-data store
    When I create object "classify-note" from fixture "markdown/valid.md" with description "Classify note" and classify "projects/demo"
    Then the command succeeds
    And a classify tag file with tag "inherited" beside object "classify-note"
    And object "classify-note" has no tags
