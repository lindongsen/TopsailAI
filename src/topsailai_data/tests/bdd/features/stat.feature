Feature: Object usage statistics

  Statistics are stored per object identity in the metadata tree. Read
  operations increment read_count, write operations increment write_count, and
  list/search never change counters. Statistics are frozen while an object is
  deleted or ceased.

  Scenario: Create counts as a write and get counts as a read
    Given an isolated topsailai-data store
    When I create object "stat-note" from fixture "markdown/valid.md" with description "Stat note"
    Then the command succeeds
    And the stat of object "stat-note" reports read count 0 and write count 1
    When I run topsailai-data with arguments:
      | get |
      | stat-note |
      | stat-note.md |
    Then the command succeeds
    And the stat of object "stat-note" reports read count 1 and write count 1

  Scenario: List and search do not change counters
    Given an isolated topsailai-data store
    When I create object "stat-stable" from fixture "markdown/valid.md" with description "Stat stable" and tags "statstable"
    Then the command succeeds
    And I record the stat of object "stat-stable"
    When I run topsailai-data with arguments:
      | list |
      | --format |
      | json |
    Then the command succeeds
    When I run topsailai-data with arguments:
      | search |
      | statstable |
      | --format |
      | json |
    Then the command succeeds
    And the stat of object "stat-stable" is unchanged

  Scenario: Statistics are frozen while an object is deleted
    Given an isolated topsailai-data store
    When I create object "stat-frozen" from fixture "markdown/valid.md" with description "Stat frozen"
    Then the command succeeds
    When I delete object "stat-frozen" once times
    Then the command succeeds
    And I record the stat of object "stat-frozen"
    When I run topsailai-data with arguments:
      | get |
      | stat-frozen |
      | stat-frozen.md |
    Then the command fails
    And the stat of object "stat-frozen" is unchanged

  Scenario: Stat top ranks objects by write count
    Given an isolated topsailai-data store
    When I create object "stat-busy" from fixture "markdown/valid.md" with description "Busy object"
    Then the command succeeds
    When I run topsailai-data with arguments:
      | put |
      | stat-busy |
      | extra.txt |
      | --from |
      | tests/bdd/fixtures/markdown/extra.txt |
    Then the command succeeds
    When I create object "stat-idle" from fixture "markdown/alternate.md" with description "Idle object"
    Then the command succeeds
    When I run topsailai-data with arguments:
      | stat |
      | top |
      | --by |
      | write |
      | --order |
      | desc |
      | --limit |
      | 5 |
      | --format |
      | json |
    Then the command succeeds
    And the stat top ranking by write in desc order starts with "stat-busy"

  Scenario: List with stat attaches counters without changing them
    Given an isolated topsailai-data store
    When I create object "stat-attached" from fixture "markdown/valid.md" with description "Attached stat"
    Then the command succeeds
    When I run topsailai-data with arguments:
      | list |
      | --with-stat |
      | --format |
      | json |
    Then the command succeeds
    And the JSON list with stat contains object "stat-attached" with read count 0 and write count 1
    And I record the stat of object "stat-attached"
    When I run topsailai-data with arguments:
      | list |
      | --with-stat |
      | --format |
      | json |
    Then the command succeeds
    And the stat of object "stat-attached" is unchanged

  Scenario Outline: Stat top rejects invalid options
    Given an isolated topsailai-data store
    When I run topsailai-data with arguments:
      | stat |
      | top |
      | <flag> |
      | <value> |
    Then the command fails with "<error>"

    Examples:
      | flag | value | error |
      | --by | nope | invalid by |
      | --order | nope | invalid order |
      | --status | nope | invalid status |
      | --limit | -1 | limit must be non-negative |
