Feature: Binary payload fidelity and archive recovery

  get writes raw bytes without text conversion, so binary payloads survive a
  round trip. recover --from restores a deleted object from an external archive
  and rejects archives that overlap the object directory.

  Scenario: A binary payload round-trips byte for byte
    Given an isolated topsailai-data store
    When I create object "binary-note" from fixture "markdown/valid.md" with description "Binary note"
    Then the command succeeds
    And a scenario binary file "payload.bin" with hex bytes "000102fffe0a0d"
    When I put scenario file "payload.bin" into object "binary-note" as "payload.bin"
    Then the command succeeds
    And object "binary-note" file "payload.bin" equals scenario binary file "payload.bin"

  Scenario: Recover restores a deleted object from an external archive
    Given an isolated topsailai-data store
    When I create object "restore-note" from fixture "markdown/valid.md" with description "Restore note"
    Then the command succeeds
    When I delete object "restore-note" once times
    Then the command succeeds
    And a scenario archive "restore.tar" containing file "restore-note.md" with content "restored markdown\n"
    When I recover object "restore-note" from scenario archive "restore.tar"
    Then the command succeeds
    And the JSON list contains object "restore-note" with description "Restore note" and status "active"
    When I run topsailai-data with arguments:
      | get |
      | restore-note |
      | restore-note.md |
    Then the command succeeds
    And stdout contains "restored markdown"

  Scenario: Recover rejects an archive that overlaps the object directory
    Given an isolated topsailai-data store
    When I create object "restore-overlap" from fixture "markdown/valid.md" with description "Restore overlap"
    Then the command succeeds
    When I delete object "restore-overlap" once times
    Then the command succeeds
    When I recover object "restore-overlap" from an overlapping archive
    Then the command fails with "archive source overlaps object data"
    And the JSON list including deleted objects contains object "restore-overlap" with description "Restore overlap" and status "deleted"
