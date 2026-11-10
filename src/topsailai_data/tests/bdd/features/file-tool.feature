Feature: File and folder capabilities inside a data object

  The file command group exposes the same capabilities as the TopsailAI file
  tool, scoped to the actual data of one data object. Every subcommand requires
  --object <id>, and every path is relative to that object's folder.

  Every scenario runs the real CLI binary against an isolated store, so the
  assertions cover argument parsing, object scoping, boundary configuration, and
  output formatting rather than the library alone. Object content is created
  through the create command and verified through the get command, so the
  scenarios exercise the public surface end to end.

  Scenario: Reject a file command without an object
    Given an isolated topsailai-data store
    When I run the file command with arguments:
      | read |
      | demo.md |
    Then the command fails with "--object <id> is required"

  Scenario: Reject an explicitly empty object value
    Given an isolated topsailai-data store
    When I run the file command with arguments:
      | read |
      | demo.md |
      | --object |
      |  |
    Then the command fails with "--object <id> is required"

  Scenario: Reject an unknown object
    Given an isolated topsailai-data store
    When I run the file command with arguments:
      | read |
      | demo.md |
      | --object |
      | absent |
    Then the command fails with "object not found"

  Scenario: Read a whole file inside an object
    Given an isolated topsailai-data store
    And an object "demo" with files:
      | path         | content       |
      | notes/read.md | alpha\nbeta\n |
    When I run the file command with arguments:
      | read |
      | notes/read.md |
      | --object |
      | demo |
    Then the command succeeds
    And stdout contains "alpha"
    And stdout contains "beta"

  Scenario: Read a byte window with seek and size
    Given an isolated topsailai-data store
    And an object "demo" with files:
      | path           | content    |
      | notes/window.md | 0123456789 |
    When I run the file command with arguments:
      | read |
      | notes/window.md |
      | --object |
      | demo |
      | --seek |
      | 2 |
      | --size |
      | 3 |
    Then the command succeeds
    And stdout contains "234"
    And stdout does not contain "0123"

  Scenario: Read from a negative seek offset
    Given an isolated topsailai-data store
    And an object "demo" with files:
      | path         | content    |
      | notes/tail.md | 0123456789 |
    When I run the file command with arguments:
      | read |
      | notes/tail.md |
      | --object |
      | demo |
      | --seek |
      | -3 |
    Then the command succeeds
    And stdout contains "789"

  Scenario: Truncate content whose extension is not whitelisted
    Given an isolated topsailai-data store
    And an object "demo" with file "notes/blob.bin" repeated 40000 times as "x"
    When I run the file command with arguments:
      | read |
      | notes/blob.bin |
      | --object |
      | demo |
    Then the command succeeds
    And stdout contains "force to truncate"

  Scenario: Read a line range
    Given an isolated topsailai-data store
    And an object "demo" with files:
      | path          | content                      |
      | notes/lines.md | alpha\nbeta\ngamma\ndelta\n |
    When I run the file command with arguments:
      | read-lines |
      | notes/lines.md |
      | --object |
      | demo |
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
    And an object "demo" with files:
      | path          | content                      |
      | notes/lines.md | alpha\nbeta\ngamma\ndelta\n |
    When I run the file command with arguments:
      | read-lines |
      | notes/lines.md |
      | --object |
      | demo |
      | --start |
      | 3 |
      | --end |
      | -1 |
    Then the command succeeds
    And stdout contains "3-gamma"
    And stdout contains "4-delta"

  Scenario: Read only the start line when no end is given
    Given an isolated topsailai-data store
    And an object "demo" with files:
      | path          | content               |
      | notes/lines.md | alpha\nbeta\ngamma\n |
    When I run the file command with arguments:
      | read-lines |
      | notes/lines.md |
      | --object |
      | demo |
      | --start |
      | 2 |
    Then the command succeeds
    And stdout contains "2-beta"
    And stdout does not contain "3-gamma"

  Scenario: Read only the start line when the end is zero
    Given an isolated topsailai-data store
    And an object "demo" with files:
      | path          | content               |
      | notes/lines.md | alpha\nbeta\ngamma\n |
    When I run the file command with arguments:
      | read-lines |
      | notes/lines.md |
      | --object |
      | demo |
      | --start |
      | 2 |
      | --end |
      | 0 |
    Then the command succeeds
    And stdout contains "2-beta"
    And stdout does not contain "3-gamma"

  Scenario: Reject an end line that is a negative sentinel other than minus one
    Given an isolated topsailai-data store
    And an object "demo" with files:
      | path          | content               |
      | notes/lines.md | alpha\nbeta\ngamma\n |
    When I run the file command with arguments:
      | read-lines |
      | notes/lines.md |
      | --object |
      | demo |
      | --start |
      | 1 |
      | --end |
      | -5 |
    Then the command fails with "must be -1, 0, or a positive line number"

  Scenario: Read context around a line
    Given an isolated topsailai-data store
    And an object "demo" with files:
      | path           | content                      |
      | notes/around.md | alpha\nbeta\ngamma\ndelta\n |
    When I run the file command with arguments:
      | read-around |
      | notes/around.md |
      | 2 |
      | --object |
      | demo |
      | --context |
      | 1 |
    Then the command succeeds
    And stdout contains "1-alpha"
    And stdout contains "2:beta"
    And stdout contains "3-gamma"

  Scenario: Reject a line number outside the file
    Given an isolated topsailai-data store
    And an object "demo" with files:
      | path           | content |
      | notes/around.md | alpha\n |
    When I run the file command with arguments:
      | read-around |
      | notes/around.md |
      | 9 |
      | --object |
      | demo |
    Then the command fails with "out of range"

  Scenario: Read lines matching a pattern with context
    Given an isolated topsailai-data store
    And an object "demo" with files:
      | path            | content                      |
      | notes/context.md | alpha\nbeta\ngamma\ndelta\n |
    When I run the file command with arguments:
      | read-context |
      | notes/context.md |
      | beta |
      | --object |
      | demo |
      | --context |
      | 1 |
    Then the command succeeds
    And stdout contains "2:beta"
    And stdout contains "1-alpha"
    And stdout contains "3-gamma"

  Scenario: Match a pattern case-insensitively by default
    Given an isolated topsailai-data store
    And an object "demo" with files:
      | path            | content      |
      | notes/context.md | Alpha\nbeta\n |
    When I run the file command with arguments:
      | read-context |
      | notes/context.md |
      | alpha |
      | --object |
      | demo |
    Then the command succeeds
    And stdout contains "1:Alpha"

  Scenario: Match a pattern case-sensitively when requested
    Given an isolated topsailai-data store
    And an object "demo" with files:
      | path            | content      |
      | notes/context.md | Alpha\nbeta\n |
    When I run the file command with arguments:
      | read-context |
      | notes/context.md |
      | alpha |
      | --object |
      | demo |
      | --case-sensitive |
    Then the command succeeds
    And stdout does not contain "Alpha"

  Scenario: Read several files at once
    Given an isolated topsailai-data store
    And an object "demo" with files:
      | path           | content |
      | notes/first.md  | one\n   |
      | notes/second.md | two\n   |
    When I run the file command with arguments:
      | read-files |
      | notes/first.md |
      | notes/second.md |
      | --object |
      | demo |
      | --format |
      | json |
    Then the command succeeds
    And stdout contains "one"
    And stdout contains "two"

  Scenario: Write a whole file inside an object
    Given an isolated topsailai-data store
    And an object "demo" with files:
      | path    | content  |
      | demo.md | markdown |
    When I run the file command with arguments:
      | write |
      | notes/written.md |
      | --object |
      | demo |
      | --content |
      | hello\n |
    Then the command succeeds
    And object "demo" file "notes/written.md" equals "hello\n"

  Scenario: Write a file from an existing source file
    Given an isolated topsailai-data store
    And an object "demo" with files:
      | path    | content  |
      | demo.md | markdown |
    And a scenario file "source.md" with content "from source\n"
    When I run the file command with arguments:
      | write |
      | notes/copied.md |
      | --object |
      | demo |
      | --from |
      | @source.md |
    Then the command succeeds
    And object "demo" file "notes/copied.md" equals "from source\n"

  Scenario: Insert content at a byte offset
    Given an isolated topsailai-data store
    And an object "demo" with files:
      | path           | content |
      | notes/insert.md | abcdef  |
    When I run the file command with arguments:
      | write |
      | notes/insert.md |
      | --object |
      | demo |
      | --content |
      | XY |
      | --seek |
      | 2 |
      | --insert |
    Then the command succeeds
    And object "demo" file "notes/insert.md" equals "abXYcdef"

  Scenario: Append content with a negative seek offset
    Given an isolated topsailai-data store
    And an object "demo" with files:
      | path           | content |
      | notes/append.md | abc     |
    When I run the file command with arguments:
      | write |
      | notes/append.md |
      | --object |
      | demo |
      | --content |
      | Z |
      | --seek |
      | -1 |
      | --insert |
    Then the command succeeds
    And object "demo" file "notes/append.md" equals "abcZ"

  Scenario: Append content to a file
    Given an isolated topsailai-data store
    And an object "demo" with files:
      | path           | content |
      | notes/append.md | one\n   |
    When I run the file command with arguments:
      | append |
      | notes/append.md |
      | --object |
      | demo |
      | --content |
      | two\n |
    Then the command succeeds
    And object "demo" file "notes/append.md" equals "one\ntwo\n"

  Scenario: Check whether files exist
    Given an isolated topsailai-data store
    And an object "demo" with files:
      | path             | content |
      | notes/present.md | x       |
    When I run the file command with arguments:
      | exists |
      | present=notes/present.md |
      | absent=notes/missing.md |
      | --object |
      | demo |
      | --format |
      | json |
    Then the command succeeds
    And exists result reports "present" as true
    And exists result reports "absent" as false

  Scenario: Reject a malformed existence check
    Given an isolated topsailai-data store
    And an object "demo" with files:
      | path    | content  |
      | demo.md | markdown |
    When I run the file command with arguments:
      | exists |
      | no-equals-sign |
      | --object |
      | demo |
    Then the command fails with "name=path"

  Scenario: Create discoverable folders with an agents marker
    Given an isolated topsailai-data store
    And an object "demo" with files:
      | path    | content  |
      | demo.md | markdown |
    When I run the file command with arguments:
      | mkdirs |
      | nested/a/b/c |
      | --object |
      | demo |
    Then the command succeeds
    And object "demo" root listing contains "nested"
    And object "demo" file "nested/a/b/c/AGENTS.md" contains "AGENTS"

  Scenario: Report a created folder as existing
    Given an isolated topsailai-data store
    And an object "demo" with files:
      | path    | content  |
      | demo.md | markdown |
    When I run the file command with arguments:
      | mkdirs |
      | nested/a/b/c |
      | --object |
      | demo |
    Then the command succeeds
    When I run the file command with arguments:
      | exists |
      | folder=nested/a/b/c |
      | marker=nested/a/b/c/AGENTS.md |
      | missing=nested/a/b/c/nope.md |
      | --object |
      | demo |
      | --format |
      | json |
    Then the command succeeds
    And exists result reports "folder" as true
    And exists result reports "marker" as true
    And exists result reports "missing" as false

  Scenario: Keep an existing agents marker when creating folders
    Given an isolated topsailai-data store
    And an object "demo" with files:
      | path             | content  |
      | demo.md          | markdown |
      | notes/AGENTS.md  | custom   |
    When I run the file command with arguments:
      | mkdirs |
      | notes |
      | --object |
      | demo |
    Then the command succeeds
    And object "demo" file "notes/AGENTS.md" equals "custom"

  Scenario: Skip the object root when creating folders
    Given an isolated topsailai-data store
    And an object "demo" with files:
      | path    | content  |
      | demo.md | markdown |
    When I run the file command with arguments:
      | mkdirs |
      | . |
      | --object |
      | demo |
    Then the command succeeds
    And object "demo" root listing does not contain "AGENTS.md"

  Scenario: List the object root
    Given an isolated topsailai-data store
    And an object "demo" with files:
      | path         | content |
      | notes/a.md   | alpha   |
      | notes/b.md   | beta    |
      | assets/c.png | binary  |
    When I run the file command with arguments:
      | list-dirs |
      | . |
      | --object |
      | demo |
      | --format |
      | json |
    Then the command succeeds
    And object "demo" root listing contains "notes"
    And object "demo" root listing contains "assets"

  Scenario: List a folder inside an object
    Given an isolated topsailai-data store
    And an object "demo" with files:
      | path       | content |
      | notes/a.md | alpha   |
      | notes/b.md | beta    |
    When I run the file command with arguments:
      | list-dirs |
      | notes |
      | --object |
      | demo |
      | --format |
      | json |
    Then the command succeeds
    And stdout contains "a.md"
    And stdout contains "b.md"

  Scenario: Report the size of a file inside an object
    Given an isolated topsailai-data store
    And an object "demo" with files:
      | path          | content |
      | notes/sized.md | 12345   |
    When I run the file command with arguments:
      | size |
      | notes/sized.md |
      | --object |
      | demo |
    Then the command succeeds
    And stdout contains "5"

  Scenario: Replace a single line and report a diff
    Given an isolated topsailai-data store
    And an object "demo" with files:
      | path         | content            |
      | notes/edit.md | one\ntwo\nthree\n |
    When I run the file command with arguments:
      | overwrite-lines |
      | notes/edit.md |
      | 2 |
      | --object |
      | demo |
      | --content |
      | TWO\n |
    Then the command succeeds
    And stdout contains "You CANNOT call continuously"
    And stdout contains "+TWO"
    And object "demo" file "notes/edit.md" equals "one\nTWO\nthree\n"

  Scenario: Replace a line range through the end of the file
    Given an isolated topsailai-data store
    And an object "demo" with files:
      | path         | content            |
      | notes/edit.md | one\ntwo\nthree\n |
    When I run the file command with arguments:
      | overwrite-lines |
      | notes/edit.md |
      | 2 |
      | --object |
      | demo |
      | --end |
      | -1 |
      | --content |
      | tail\n |
    Then the command succeeds
    And object "demo" file "notes/edit.md" equals "one\ntail\n"

  Scenario: Delete a line with empty replacement content
    Given an isolated topsailai-data store
    And an object "demo" with files:
      | path         | content            |
      | notes/edit.md | one\ntwo\nthree\n |
    When I run the file command with arguments:
      | overwrite-lines |
      | notes/edit.md |
      | 2 |
      | --object |
      | demo |
    Then the command succeeds
    And object "demo" file "notes/edit.md" equals "one\nthree\n"

  Scenario: Reject a start line beyond the file length
    Given an isolated topsailai-data store
    And an object "demo" with files:
      | path         | content |
      | notes/edit.md | one\n   |
    When I run the file command with arguments:
      | overwrite-lines |
      | notes/edit.md |
      | 5 |
      | --object |
      | demo |
      | --content |
      | x |
    Then the command fails with "exceeds file length"

  Scenario: Insert a line after a line number
    Given an isolated topsailai-data store
    And an object "demo" with files:
      | path               | content   |
      | notes/insert-line.md | one\ntwo\n |
    When I run the file command with arguments:
      | insert |
      | notes/insert-line.md |
      | 1 |
      | --object |
      | demo |
      | --content |
      | inserted\n |
    Then the command succeeds
    And stdout contains "+inserted"
    And object "demo" file "notes/insert-line.md" equals "one\ninserted\ntwo\n"

  Scenario: Insert a line before a line number
    Given an isolated topsailai-data store
    And an object "demo" with files:
      | path               | content   |
      | notes/insert-line.md | one\ntwo\n |
    When I run the file command with arguments:
      | insert |
      | notes/insert-line.md |
      | 2 |
      | --object |
      | demo |
      | --content |
      | before-two\n |
      | --before |
    Then the command succeeds
    And object "demo" file "notes/insert-line.md" equals "one\nbefore-two\ntwo\n"

  Scenario: Report the size of a written file
    Given an isolated topsailai-data store
    And an object "demo" with files:
      | path    | content  |
      | demo.md | markdown |
    When I run the file command with arguments:
      | write |
      | notes/size-check.md |
      | --object |
      | demo |
      | --content |
      | abcde |
    Then the command succeeds
    And object "demo" file "notes/size-check.md" has size 5

  Scenario: Reject an unknown file subcommand
    Given an isolated topsailai-data store
    When I run the file command with arguments:
      | nope |
    Then the command fails with "unknown file subcommand"

  Scenario: Reject a metadata marker as a write target
    Given an isolated topsailai-data store
    And an object "demo" with files:
      | path    | content  |
      | demo.md | markdown |
    When I run the file command with arguments:
      | write |
      | demo.tags |
      | --object |
      | demo |
      | --content |
      | x |
    Then the command fails with "reserved metadata marker"

  Scenario: Reject a metadata marker as a read target
    Given an isolated topsailai-data store
    And an object "demo" with files:
      | path    | content  |
      | demo.md | markdown |
    When I run the file command with arguments:
      | read |
      | .stat.json |
      | --object |
      | demo |
    Then the command fails with "reserved metadata marker"

  Scenario: Write a file from redirected stdin
    Given an isolated topsailai-data store
    And an object "demo" with files:
      | path    | content  |
      | demo.md | markdown |
    When I run the file command with stdin "piped content\n" and arguments:
      | write |
      | notes/from-stdin.md |
      | --object |
      | demo |
    Then the command succeeds
    And object "demo" file "notes/from-stdin.md" equals "piped content\n"

  Scenario: Append to a file from redirected stdin
    Given an isolated topsailai-data store
    And an object "demo" with files:
      | path                | content |
      | notes/append-stdin.md | one\n   |
    When I run the file command with stdin "two\n" and arguments:
      | append |
      | notes/append-stdin.md |
      | --object |
      | demo |
    Then the command succeeds
    And object "demo" file "notes/append-stdin.md" equals "one\ntwo\n"

  Scenario: Replace a line range from redirected stdin
    Given an isolated topsailai-data store
    And an object "demo" with files:
      | path                   | content            |
      | notes/overwrite-stdin.md | one\ntwo\nthree\n |
    When I run the file command with stdin "TWO\n" and arguments:
      | overwrite-lines |
      | notes/overwrite-stdin.md |
      | 2 |
      | --object |
      | demo |
    Then the command succeeds
    And object "demo" file "notes/overwrite-stdin.md" equals "one\nTWO\nthree\n"

  Scenario: Insert a line from redirected stdin
    Given an isolated topsailai-data store
    And an object "demo" with files:
      | path                | content   |
      | notes/insert-stdin.md | one\ntwo\n |
    When I run the file command with stdin "inserted\n" and arguments:
      | insert |
      | notes/insert-stdin.md |
      | 1 |
      | --object |
      | demo |
    Then the command succeeds
    And object "demo" file "notes/insert-stdin.md" equals "one\ninserted\ntwo\n"

  Scenario: Write a file from stdin through the from flag
    Given an isolated topsailai-data store
    And an object "demo" with files:
      | path    | content  |
      | demo.md | markdown |
    When I run the file command with stdin "dash content\n" and arguments:
      | write |
      | notes/from-dash.md |
      | --object |
      | demo |
      | --from |
      | - |
    Then the command succeeds
    And object "demo" file "notes/from-dash.md" equals "dash content\n"

  Scenario: Explicit empty content wins over redirected stdin
    Given an isolated topsailai-data store
    And an object "demo" with files:
      | path              | content   |
      | notes/empty-wins.md | existing\n |
    When I run the file command with stdin "ignored\n" and arguments:
      | write |
      | notes/empty-wins.md |
      | --object |
      | demo |
      | --content |
      |  |
    Then the command succeeds
    And object "demo" file "notes/empty-wins.md" equals ""

  Scenario: The from flag wins over inline content
    Given an isolated topsailai-data store
    And an object "demo" with files:
      | path    | content  |
      | demo.md | markdown |
    And a scenario file "precedence-src.md" with content "from-file\n"
    When I run the file command with arguments:
      | write |
      | notes/precedence-out.md |
      | --object |
      | demo |
      | --content |
      | inline |
      | --from |
      | @precedence-src.md |
    Then the command succeeds
    And object "demo" file "notes/precedence-out.md" equals "from-file\n"

  Scenario: A written file appears in the object folder listing
    Given an isolated topsailai-data store
    And an object "demo" with files:
      | path    | content  |
      | demo.md | markdown |
    When I run the file command with arguments:
      | write |
      | notes/visible.md |
      | --object |
      | demo |
      | --content |
      | body |
    Then the command succeeds
    And object "demo" root listing contains "notes"

  Scenario: A file written through the file command is readable through get
    Given an isolated topsailai-data store
    And an object "demo" with files:
      | path    | content  |
      | demo.md | markdown |
    When I run the file command with arguments:
      | write |
      | notes/shared.md |
      | --object |
      | demo |
      | --content |
      | shared body |
    Then the command succeeds
    And object "demo" file "notes/shared.md" equals "shared body"

  Scenario: A file written through put is readable through the file command
    Given an isolated topsailai-data store
    And an object "demo" with files:
      | path    | content  |
      | demo.md | markdown |
    And a scenario file "put-source.md" with content "put body\n"
    When I run topsailai-data with arguments:
      | put |
      | demo |
      | notes/from-put.md |
      | --from |
      | @put-source.md |
    Then the command succeeds
    When I run the file command with arguments:
      | read |
      | notes/from-put.md |
      | --object |
      | demo |
    Then the command succeeds
    And stdout contains "put body"

  Scenario: Reject a path that tries to leave the object
    Given an isolated topsailai-data store
    And an object "demo" with files:
      | path    | content  |
      | demo.md | markdown |
    When I run the file command with arguments:
      | read |
      | ../outside.md |
      | --object |
      | demo |
    Then the command fails with "object not found"

  Scenario: Read a file whose name matches the object marker
    Given an isolated topsailai-data store
    And an object "demo" with files:
      | path    | content  |
      | demo.md | markdown |
    When I run the file command with arguments:
      | read |
      | demo.md |
      | --object |
      | demo |
    Then the command succeeds
    And stdout contains "markdown"
