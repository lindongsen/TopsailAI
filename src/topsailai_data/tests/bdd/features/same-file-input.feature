Feature: Reject same-file put input

  Scenario: Preserve an object marker when it is used as its own put source
    Given an isolated topsailai-data store
    When I create object "same-file-note" from fixture "markdown/valid.md" with description "Same file regression"
    Then the command succeeds
    When I put object "same-file-note" using its own marker as the source
    Then the command fails with "source and destination are the same file"
    When I get object "same-file-note" marker
    Then the command succeeds
    And stdout contains "# Smoke test content"
