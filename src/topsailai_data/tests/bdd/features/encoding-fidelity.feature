Feature: UTF-8 fidelity beyond the encoding detection sample

  Encoding detection samples only the first 32768 bytes of a file. When that
  sample is pure ASCII it carries no encoding evidence, so the detected charset
  is arbitrary and applying it to the whole buffer corrupts any non-ASCII
  character that appears later. These scenarios pin the required behaviour: a
  file that is valid UTF-8 must read back byte for byte regardless of where its
  non-ASCII bytes sit, and a file with a stray invalid byte must keep its valid
  runs instead of losing them.

  Every scenario runs the real CLI binary against an isolated store and asserts
  on CLI output only. Object content is created through create and verified
  through get and the file command group, so the scenarios exercise the public
  surface end to end.

  Scenario: A box-drawing character after the sample boundary survives read
    Given an isolated topsailai-data store
    And a scenario file "boundary.md" with 66000 ASCII bytes and "│" at byte 40000
    When I create object "boundary" from scenario file "boundary.md" with description "Boundary probe"
    Then the command succeeds
    And the file read of "boundary.md" in object "boundary" equals scenario file "boundary.md"

  Scenario Outline: A box-drawing character at the sample boundary survives read
    Given an isolated topsailai-data store
    And a scenario file "edge.md" with 66000 ASCII bytes and "│" at byte <offset>
    When I create object "edge" from scenario file "edge.md" with description "Edge probe"
    Then the command succeeds
    And the file read of "edge.md" in object "edge" equals scenario file "edge.md"

    Examples:
      | offset |
      | 32765  |
      | 32766  |
      | 32767  |
      | 40000  |

  Scenario: CJK text after the sample boundary survives read
    Given an isolated topsailai-data store
    And a scenario file "cjk.md" with 66000 ASCII bytes and "中文测试" at byte 40000
    When I create object "cjk" from scenario file "cjk.md" with description "CJK probe"
    Then the command succeeds
    And the file read of "cjk.md" in object "cjk" equals scenario file "cjk.md"

  Scenario: Every read subcommand preserves content beyond the sample boundary
    Given an isolated topsailai-data store
    And a scenario file "family.md" with 66000 ASCII bytes and "│" at byte 40000
    When I create object "family" from scenario file "family.md" with description "Family probe"
    Then the command succeeds
    And the file read-lines of "family.md" in object "family" contains "│"
    And the file read-around of "family.md" in object "family" at line 1 contains "│"
    And the file read-context of "family.md" in object "family" matching "a" contains "│"
    And the file read-files of "family.md" in object "family" contains "│"

  Scenario: A stray invalid byte does not destroy surrounding UTF-8
    Given an isolated topsailai-data store
    And a scenario file "mixed.md" with 66000 ASCII bytes and "│" at byte 40000 and an invalid byte at byte 50000
    When I create object "mixed" from scenario file "mixed.md" with description "Mixed probe"
    Then the command succeeds
    And the file read of "mixed.md" in object "mixed" contains "│"

  Scenario: A non-UTF-8 sample still uses detected decoding
    Given an isolated topsailai-data store
    And a scenario latin1 file "latin1.md" with content "Le café est très bon. Voilà la crème brûlée. Le café est très bon. Voilà la crème brûlée. "
    When I create object "latin1" from scenario file "latin1.md" with description "Latin1 probe"
    Then the command succeeds
    And the file read of "latin1.md" in object "latin1" contains "café"

  Scenario: A read-modify-write cycle preserves the original content
    Given an isolated topsailai-data store
    And a scenario file "rmw.md" with 66000 ASCII bytes and "│" at byte 40000
    When I create object "rmw" from scenario file "rmw.md" with description "RMW probe"
    Then the command succeeds
    And the file read of "rmw.md" in object "rmw" equals scenario file "rmw.md"
    When I put the file read of "rmw.md" in object "rmw" back as "rmw.md"
    Then the command succeeds
    And object "rmw" file "rmw.md" equals scenario file "rmw.md"
