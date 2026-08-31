Feature: Lifecycle and garbage collection

  Scenario: Soft delete hides an object while include-deleted exposes it
    Given an isolated topsailai-data store
    When I create object "soft-deleted" from fixture "markdown/valid.md" with description "Preserved description" and tags "lifecycle"
    Then the command succeeds
    When I delete object "soft-deleted" once times
    Then the command succeeds
    And the JSON list including deleted objects contains object "soft-deleted" with description "Preserved description" and status "deleted"
    When I run topsailai-data with arguments:
      | list |
      | --format |
      | json |
    Then the command succeeds
    And the JSON list has exactly IDs ""
    When I run topsailai-data with arguments:
      | search |
      | lifecycle |
      | --format |
      | json |
    Then the command succeeds
    And the JSON search result has exactly IDs ""
    When I run topsailai-data with arguments:
      | list |
      | --include-deleted |
      | --format |
      | json |
    Then the command succeeds
    And the JSON list has exactly IDs "soft-deleted"

  Scenario: Show deleted and ceased objects exposes metadata but not actual data
    Given an isolated topsailai-data store
    When I create object "deleted-show" from fixture "markdown/valid.md" with description "Deleted metadata"
    Then the command succeeds
    When I delete object "deleted-show" once times
    Then the command succeeds
    When I run topsailai-data with arguments:
      | show |
      | deleted-show |
    Then the command succeeds
    And stdout contains "Status:        deleted"
    And stdout contains "Actual data unavailable for deleted object"
    And stdout does not contain "--- Markdown ---"
    And stdout does not contain "--- folder structure ---"
    When I delete object "deleted-show" once times
    Then the command succeeds
    When I run topsailai-data with arguments:
      | show |
      | deleted-show |
    Then the command succeeds
    And stdout contains "Status:        ceased"
    And stdout contains "Actual data unavailable for ceased object"
    And stdout does not contain "--- Markdown ---"
    And stdout does not contain "--- folder structure ---"

  Scenario: Recover restores deleted status and preserved markdown content
    Given an isolated topsailai-data store
    When I create object "recoverable" from fixture "markdown/valid.md" with description "Recoverable object"
    Then the command succeeds
    When I delete object "recoverable" once times
    Then the command succeeds
    When I run topsailai-data with arguments:
      | recover |
      | recoverable |
    Then the command succeeds
    And the JSON list contains object "recoverable" with description "Recoverable object" and status "active"
    When I run topsailai-data with arguments:
      | get |
      | recoverable |
      | recoverable.md |
    Then the command succeeds
    And stdout contains "Smoke test content"

  Scenario: Recover rejects active and ceased objects
    Given an isolated topsailai-data store
    When I create object "active-recover" from fixture "markdown/valid.md" with description "Active object"
    Then the command succeeds
    When I run topsailai-data with arguments:
      | recover |
      | active-recover |
    Then the command fails with "already active"
    When I create object "ceased-recover" from fixture "markdown/valid.md" with description "Ceased object"
    Then the command succeeds
    When I delete object "ceased-recover" twice times
    Then the command succeeds
    When I run topsailai-data with arguments:
      | recover |
      | ceased-recover |
    Then the command fails with "ceased"

  Scenario: Ceased objects reject actual-data commands after repeated delete
    Given an isolated topsailai-data store
    When I create object "ceased-data" from fixture "markdown/valid.md" with description "Ceased data"
    Then the command succeeds
    When I delete object "ceased-data" twice times
    Then the command succeeds
    When I run topsailai-data with arguments:
      | get |
      | ceased-data |
      | ceased-data.md |
    Then the command fails
    When I run topsailai-data with arguments:
      | put |
      | ceased-data |
      | extra.txt |
      | --from |
      | tests/bdd/fixtures/markdown/extra.txt |
    Then the command fails
    When I run topsailai-data with arguments:
      | get-archive |
      | ceased-data |
    Then the command fails

  Scenario: Dry-run GC does not finalize a deleted object
    Given an isolated topsailai-data store
    When I create object "dry-run-deleted" from fixture "markdown/valid.md" with description "Dry run object"
    Then the command succeeds
    When I delete object "dry-run-deleted" once times
    Then the command succeeds
    When I run topsailai-data with arguments:
      | gc |
      | --status |
      | deleted |
      | --dry-run |
    Then the command succeeds
    And stdout contains "dry-run"
    And the JSON list including deleted objects contains object "dry-run-deleted" with description "Dry run object" and status "deleted"

  Scenario: Targeted deleted GC finalizes only deleted objects
    Given an isolated topsailai-data store
    When I create object "gc-deleted" from fixture "markdown/valid.md" with description "Deleted candidate"
    Then the command succeeds
    When I create object "gc-active" from fixture "markdown/alternate.md" with description "Active survivor"
    Then the command succeeds
    When I delete object "gc-deleted" once times
    Then the command succeeds
    When I run topsailai-data with arguments:
      | gc |
      | --status |
      | deleted |
    Then the command succeeds
    And the JSON list including deleted objects contains object "gc-deleted" with description "Deleted candidate" and status "ceased"
    And the JSON list including deleted objects contains object "gc-active" with description "Active survivor" and status "active"

  Scenario: Ceased GC removes only ceased objects immediately
    Given an isolated topsailai-data store
    When I create object "gc-ceased" from fixture "markdown/valid.md" with description "Ceased candidate"
    Then the command succeeds
    When I create object "gc-survivor" from fixture "markdown/alternate.md" with description "Active survivor"
    Then the command succeeds
    When I delete object "gc-ceased" twice times
    Then the command succeeds
    When I run topsailai-data with arguments:
      | gc |
      | --status |
      | ceased |
    Then the command succeeds
    And the JSON list including deleted objects contains object "gc-survivor" with description "Active survivor" and status "active"
    When I run topsailai-data with arguments:
      | show |
      | gc-ceased |
    Then the command fails

  Scenario: Default GC retains a fresh ceased object within the configured retention window
    Given an isolated topsailai-data store
    When I create object "fresh-ceased" from fixture "markdown/valid.md" with description "Fresh ceased object"
    Then the command succeeds
    When I delete object "fresh-ceased" twice times
    Then the command succeeds
    When I run topsailai-data with arguments:
      | gc |
    Then the command succeeds
    And the JSON list including deleted objects contains object "fresh-ceased" with description "Fresh ceased object" and status "ceased"

  Scenario: Invalid GC status has no lifecycle side effect
    Given an isolated topsailai-data store
    When I create object "invalid-gc" from fixture "markdown/valid.md" with description "Invalid GC target"
    Then the command succeeds
    When I delete object "invalid-gc" once times
    Then the command succeeds
    When I run topsailai-data with arguments:
      | gc |
      | --status |
      | active |
    Then the command fails with "invalid status"
    And the JSON list including deleted objects contains object "invalid-gc" with description "Invalid GC target" and status "deleted"
