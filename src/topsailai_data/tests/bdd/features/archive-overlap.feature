Feature: Reject overlapping archive sources

  Scenario: Preserve an active object when put-archive uses an in-object source
    Given an isolated topsailai-data store
    When I create object "archive-overlap" from fixture "markdown/valid.md" with description "Archive overlap"
    Then the command succeeds
    When I put an overlapping archive into object "archive-overlap"
    Then the command fails with "archive source overlaps object data"
    When I run topsailai-data with arguments:
      | get |
      | archive-overlap |
      | archive-overlap.md |
    Then the command succeeds
    And stdout contains "# Smoke test content"

  Scenario: Preserve deleted status when recover uses an in-object source
    Given an isolated topsailai-data store
    When I create object "recover-overlap" from fixture "markdown/valid.md" with description "Recover overlap"
    Then the command succeeds
    When I delete object "recover-overlap" once times
    Then the command succeeds
    When I recover object "recover-overlap" from an overlapping archive
    Then the command fails with "archive source overlaps object data"
    And the JSON list including deleted objects contains object "recover-overlap" with description "Recover overlap" and status "deleted"
