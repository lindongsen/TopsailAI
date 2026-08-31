Feature: Preserve the mandatory Markdown through archive updates

  Scenario: Archive without the mandatory Markdown preserves the existing marker
    Given an isolated topsailai-data store
    When I create object "archive-marker" from fixture "markdown/valid.md" with description "Archive marker"
    Then the command succeeds
    When I put a generated archive without marker into object "archive-marker"
    Then the command succeeds
    When I run topsailai-data with arguments:
      | get |
      | archive-marker |
      | archive-marker.md |
    Then the command succeeds
    And stdout contains "Smoke test content"
    When I run topsailai-data with arguments:
      | get |
      | archive-marker |
      | archive-extra.txt |
    Then the command succeeds
    And stdout contains "archive extra content"

  Scenario: Archive containing the mandatory Markdown replaces the existing marker
    Given an isolated topsailai-data store
    When I create object "archive-replacement" from fixture "markdown/valid.md" with description "Archive replacement"
    Then the command succeeds
    When I put a generated archive with marker into object "archive-replacement"
    Then the command succeeds
    When I run topsailai-data with arguments:
      | get |
      | archive-replacement |
      | archive-replacement.md |
    Then the command succeeds
    And stdout contains "replacement markdown"
