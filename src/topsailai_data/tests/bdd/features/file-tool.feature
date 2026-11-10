Feature: File and folder capabilities

  The file command group exposes the same capabilities as the TopsailAI file
  tool. Every scenario runs the real CLI binary against an isolated store, so
  the assertions cover argument parsing, boundary configuration, and output
  formatting rather than the library alone.

  Scenario: Read a whole file
    Given an isolated topsailai-data store
    And a scenario file "notes/read.md" with content "alpha\nbeta\n"
    When I run the file command with arguments:
      | read |
      | @notes/read.md |
    Then the command succeeds
    And stdout contains "alpha"
    And stdout contains "beta"

  Scenario: Read a byte window with seek and size
    Given an isolated topsailai-data store
    And a scenario file "notes/window.md" with content "0123456789"
    When I run the file command with arguments:
      | read |
      | @notes/window.md |
      | --seek |
      | 2 |
      | --size |
      | 3 |
    Then the command succeeds
    And stdout contains "234"
    And stdout does not contain "0123"

  Scenario: Read from a negative seek offset
    Given an isolated topsailai-data store
    And a scenario file "notes/tail.md" with content "0123456789"
    When I run the file command with arguments:
      | read |
      | @notes/tail.md |
      | --seek |
      | -3 |
    Then the command succeeds
    And stdout contains "789"

  Scenario: Truncate content whose extension is not whitelisted
    Given an isolated topsailai-data store
    And a scenario file "notes/blob.bin" with 40000 repeated "x"
    When I run the file command with arguments:
      | read |
      | @notes/blob.bin |
    Then the command succeeds
    And stdout contains "force to truncate"

  Scenario: Read a line range
    Given an isolated topsailai-data store
    And a scenario file "notes/lines.md" with content "alpha\nbeta\ngamma\ndelta\n"
    When I run the file command with arguments:
      | read-lines |
      | @notes/lines.md |
      | --start |
      | 2 |
      | --end |
      | 3 |
    Then the command succeeds
    And stdout contains "2-beta"
    And stdout contains "3-gamma"
    And stdout does not contain "1-alpha"

  Scenario: Read a line range through the end of the file
    Given an isolated topsailai-data store
    And a scenario file "notes/lines.md" with content "alpha\nbeta\ngamma\ndelta\n"
    When I run the file command with arguments:
      | read-lines |
      | @notes/lines.md |
      | --start |
      | 3 |
      | --end |
      | -1 |
    Then the command succeeds
    And stdout contains "3-gamma"
    And stdout contains "4-delta"

  Scenario: Read only the start line when no end is given
    Given an isolated topsailai-data store
    And a scenario file "notes/lines.md" with content "alpha\nbeta\ngamma\n"
    When I run the file command with arguments:
      | read-lines |
      | @notes/lines.md |
      | --start |
      | 2 |
    Then the command succeeds
    And stdout contains "2-beta"
    And stdout does not contain "3-gamma"

  Scenario: Read context around a line
    Given an isolated topsailai-data store
    And a scenario file "notes/around.md" with content "alpha\nbeta\ngamma\ndelta\n"
    When I run the file command with arguments:
      | read-around |
      | @notes/around.md |
      | 2 |
      | --context |
      | 1 |
    Then the command succeeds
    And stdout contains "1-alpha"
    And stdout contains "2:beta"
    And stdout contains "3-gamma"

  Scenario: Reject a line number outside the file
    Given an isolated topsailai-data store
    And a scenario file "notes/around.md" with content "alpha\n"
    When I run the file command with arguments:
      | read-around |
      | @notes/around.md |
      | 9 |
    Then the command fails with "out of range"

  Scenario: Read lines matching a pattern with context
    Given an isolated topsailai-data store
    And a scenario file "notes/context.md" with content "alpha\nbeta\ngamma\ndelta\n"
    When I run the file command with arguments:
      | read-context |
      | @notes/context.md |
      | beta |
      | --context |
      | 1 |
    Then the command succeeds
    And stdout contains "2:beta"
    And stdout contains "1-alpha"
    And stdout contains "3-gamma"

  Scenario: Match a pattern case-insensitively by default
    Given an isolated topsailai-data store
    And a scenario file "notes/context.md" with content "Alpha\nbeta\n"
    When I run the file command with arguments:
      | read-context |
      | @notes/context.md |
      | alpha |
    Then the command succeeds
    And stdout contains "1:Alpha"

  Scenario: Match a pattern case-sensitively when requested
    Given an isolated topsailai-data store
    And a scenario file "notes/context.md" with content "Alpha\nbeta\n"
    When I run the file command with arguments:
      | read-context |
      | @notes/context.md |
      | alpha |
      | --case-sensitive |
    Then the command succeeds
    And stdout does not contain "Alpha"

  Scenario: Read several files at once
    Given an isolated topsailai-data store
    And a scenario file "notes/first.md" with content "one\n"
    And a scenario file "notes/second.md" with content "two\n"
    When I run the file command with arguments:
      | read-files |
      | @notes/first.md |
      | @notes/second.md |
      | --format |
      | json |
    Then the command succeeds
    And stdout contains "one"
    And stdout contains "two"

  Scenario: Write a whole file
    Given an isolated topsailai-data store
    When I run the file command with arguments:
      | write |
      | @notes/written.md |
      | --content |
      | hello\n |
    Then the command succeeds
    And scenario file "notes/written.md" equals "hello\n"

  Scenario: Write a file from an existing source file
    Given an isolated topsailai-data store
    And a scenario file "notes/source.md" with content "from source\n"
    When I run the file command with arguments:
      | write |
      | @notes/copied.md |
      | --from |
      | @notes/source.md |
    Then the command succeeds
    And scenario file "notes/copied.md" equals "from source\n"

  Scenario: Insert content at a byte offset
    Given an isolated topsailai-data store
    And a scenario file "notes/insert.md" with content "abcdef"
    When I run the file command with arguments:
      | write |
      | @notes/insert.md |
      | --content |
      | XY |
      | --seek |
      | 2 |
      | --insert |
    Then the command succeeds
    And scenario file "notes/insert.md" equals "abXYcdef"

  Scenario: Append content with a negative seek offset
    Given an isolated topsailai-data store
    And a scenario file "notes/append.md" with content "abc"
    When I run the file command with arguments:
      | write |
      | @notes/append.md |
      | --content |
      | Z |
      | --seek |
      | -1 |
      | --insert |
    Then the command succeeds
    And scenario file "notes/append.md" equals "abcZ"

  Scenario: Append content to a file
    Given an isolated topsailai-data store
    And a scenario file "notes/append.md" with content "one\n"
    When I run the file command with arguments:
      | append |
      | @notes/append.md |
      | --content |
      | two\n |
    Then the command succeeds
    And scenario file "notes/append.md" equals "one\ntwo\n"

  Scenario: Check whether files exist
    Given an isolated topsailai-data store
    And a scenario file "notes/present.md" with content "x"
    When I run the file command with arguments:
      | exists |
      | present=@notes/present.md |
      | absent=@notes/missing.md |
      | --format |
      | json |
    Then the command succeeds
    And stdout contains "present"
    And stdout contains "absent"

  Scenario: Reject a malformed existence check
    Given an isolated topsailai-data store
    When I run the file command with arguments:
      | exists |
      | no-equals-sign |
    Then the command fails with "name=path"

  Scenario: Create folders
    Given an isolated topsailai-data store
    When I run the file command with arguments:
      | mkdirs |
      | @nested/a/b/c |
    Then the command succeeds
    And scenario folder "nested/a/b/c" exists

  Scenario: Reject a relative folder path
    Given an isolated topsailai-data store
    When I run the file command with arguments:
      | mkdirs |
      | relative/dir |
    Then the command fails with "absolute"

  Scenario: List several folders
    Given an isolated topsailai-data store
    And a scenario file "listing/b.md" with content "x"
    And a scenario file "listing/a.md" with content "x"
    When I run the file command with arguments:
      | list-dirs |
      | @listing |
      | --format |
      | json |
    Then the command succeeds
    And stdout contains "a.md"
    And stdout contains "b.md"

  Scenario: Report the size of a file
    Given an isolated topsailai-data store
    And a scenario file "notes/sized.md" with content "12345"
    When I run the file command with arguments:
      | size |
      | @notes/sized.md |
    Then the command succeeds
    And stdout contains "5"

  Scenario: Replace a single line and report a diff
    Given an isolated topsailai-data store
    And a scenario file "notes/edit.md" with content "one\ntwo\nthree\n"
    When I run the file command with arguments:
      | overwrite-lines |
      | @notes/edit.md |
      | 2 |
      | --content |
      | TWO\n |
    Then the command succeeds
    And stdout contains "You CANNOT call continuously"
    And stdout contains "+TWO"
    And scenario file "notes/edit.md" equals "one\nTWO\nthree\n"

  Scenario: Replace a line range through the end of the file
    Given an isolated topsailai-data store
    And a scenario file "notes/edit.md" with content "one\ntwo\nthree\n"
    When I run the file command with arguments:
      | overwrite-lines |
      | @notes/edit.md |
      | 2 |
      | --end |
      | -1 |
      | --content |
      | tail\n |
    Then the command succeeds
    And scenario file "notes/edit.md" equals "one\ntail\n"

  Scenario: Delete a line with empty replacement content
    Given an isolated topsailai-data store
    And a scenario file "notes/edit.md" with content "one\ntwo\nthree\n"
    When I run the file command with arguments:
      | overwrite-lines |
      | @notes/edit.md |
      | 2 |
    Then the command succeeds
    And scenario file "notes/edit.md" equals "one\nthree\n"

  Scenario: Reject a start line beyond the file length
    Given an isolated topsailai-data store
    And a scenario file "notes/edit.md" with content "one\n"
    When I run the file command with arguments:
      | overwrite-lines |
      | @notes/edit.md |
      | 5 |
      | --content |
      | x |
    Then the command fails with "exceeds file length"

  Scenario: Insert a line after a line number
    Given an isolated topsailai-data store
    And a scenario file "notes/insert-line.md" with content "one\ntwo\n"
    When I run the file command with arguments:
      | insert |
      | @notes/insert-line.md |
      | 1 |
      | --content |
      | inserted\n |
    Then the command succeeds
    And stdout contains "+inserted"
    And scenario file "notes/insert-line.md" equals "one\ninserted\ntwo\n"

  Scenario: Insert a line before a line number
    Given an isolated topsailai-data store
    And a scenario file "notes/insert-line.md" with content "one\ntwo\n"
    When I run the file command with arguments:
      | insert |
      | @notes/insert-line.md |
      | 2 |
      | --content |
      | before-two\n |
      | --before |
    Then the command succeeds
    And scenario file "notes/insert-line.md" equals "one\nbefore-two\ntwo\n"

  Scenario: Report the size of a written file
    Given an isolated topsailai-data store
    When I run the file command with arguments:
      | write |
      | @notes/size-check.md |
      | --content |
      | abcde |
    Then the command succeeds
    And scenario file "notes/size-check.md" has size 5

  Scenario: Reject an unknown file subcommand
    Given an isolated topsailai-data store
    When I run the file command with arguments:
      | nope |
    Then the command fails with "unknown file subcommand"

  Scenario: Write a file from redirected stdin
    Given an isolated topsailai-data store
    When I run the file command with stdin "piped content\n" and arguments:
      | write |
      | @notes/from-stdin.md |
    Then the command succeeds
    And scenario file "notes/from-stdin.md" equals "piped content\n"

  Scenario: Append to a file from redirected stdin
    Given an isolated topsailai-data store
    And a scenario file "notes/append-stdin.md" with content "one\n"
    When I run the file command with stdin "two\n" and arguments:
      | append |
      | @notes/append-stdin.md |
    Then the command succeeds
    And scenario file "notes/append-stdin.md" equals "one\ntwo\n"

  Scenario: Replace a line range from redirected stdin
    Given an isolated topsailai-data store
    And a scenario file "notes/overwrite-stdin.md" with content "one\ntwo\nthree\n"
    When I run the file command with stdin "TWO\n" and arguments:
      | overwrite-lines |
      | @notes/overwrite-stdin.md |
      | 2 |
    Then the command succeeds
    And scenario file "notes/overwrite-stdin.md" equals "one\nTWO\nthree\n"

  Scenario: Insert a line from redirected stdin
    Given an isolated topsailai-data store
    And a scenario file "notes/insert-stdin.md" with content "one\ntwo\n"
    When I run the file command with stdin "inserted\n" and arguments:
      | insert |
      | @notes/insert-stdin.md |
      | 1 |
    Then the command succeeds
    And scenario file "notes/insert-stdin.md" equals "one\ninserted\ntwo\n"

  Scenario: Write a file from stdin through the from flag
    Given an isolated topsailai-data store
    When I run the file command with stdin "dash content\n" and arguments:
      | write |
      | @notes/from-dash.md |
      | --from |
      | - |
    Then the command succeeds
    And scenario file "notes/from-dash.md" equals "dash content\n"

  Scenario: Explicit empty content wins over redirected stdin
    Given an isolated topsailai-data store
    And a scenario file "notes/empty-wins.md" with content "existing\n"
    When I run the file command with stdin "ignored\n" and arguments:
      | write |
      | @notes/empty-wins.md |
      | --content |
      |  |
    Then the command succeeds
    And scenario file "notes/empty-wins.md" equals ""

  Scenario: The from flag wins over inline content
    Given an isolated topsailai-data store
    And a scenario file "notes/precedence-src.md" with content "from-file\n"
    When I run the file command with arguments:
      | write |
      | @notes/precedence-out.md |
      | --content |
      | inline |
      | --from |
      | @notes/precedence-src.md |
    Then the command succeeds
    And scenario file "notes/precedence-out.md" equals "from-file\n"
