Feature: Read files without consuming disproportionate resources
  The Node commonly runs on a personal computer and the Server serves several
  callers. A permitted whole-file read must preserve exact output while keeping
  memory bounded, avoiding redundant wire expansion, and leaving capacity for
  unrelated small requests.

  Scenario: A large file is streamed with bounded memory
    Given an authorized caller and a readable 256 MiB file
    When the caller reads the whole file to a destination
    Then the destination is byte-identical to the source
    And Node, Server, and CLI memory stay within the documented streaming budget

  Scenario: An exact chunk boundary terminates cleanly
    Given an authorized caller and a readable file exactly one transfer chunk long
    When the caller reads the whole file to a destination
    Then the destination is byte-identical to the source
    And the transfer terminates without an unbounded extra request

  Scenario: A final partial chunk is preserved
    Given an authorized caller and a readable file one byte longer than one transfer chunk
    When the caller reads the whole file to a destination
    Then the destination is byte-identical to the source
    And the final byte appears exactly once

  Scenario: A mid-transfer failure does not publish a partial destination
    Given an authorized caller, a readable large file, and an existing destination
    When the transfer fails after at least one chunk
    Then the existing destination remains unchanged
    And no temporary output remains

  Scenario: Efficient transport stays within the wire budget
    Given an authorized caller and a readable 16 MiB incompressible file
    When the caller reads the whole file without transport encryption
    Then the destination is byte-identical to the source
    And protocol bytes stay within the documented expansion budget

  Scenario: Efficient transport preserves authentication
    Given a caller with an invalid proof and a readable file
    When the caller requests the file through the efficient transport
    Then the request is refused as unauthenticated
    And no file content is transferred

  Scenario: Efficient transport preserves Node authorization
    Given an authenticated caller without read permission and a readable file
    When the caller requests the file through the efficient transport
    Then the request is refused as denied
    And no file content is transferred

  Scenario: Efficient transport preserves the path fence
    Given an authorized caller requests a path that escapes its scope
    When the caller requests the file through the efficient transport
    Then the request is refused as denied
    And no outside file content is transferred

  Scenario: Concurrent large reads leave capacity for metadata
    Given eight authorized large reads are active
    When another authorized caller requests file metadata
    Then the metadata response meets the documented latency budget
    And every large read remains byte-identical

  Scenario: One caller cannot consume all read capacity
    Given one caller has reached its active-read limit
    And Server capacity remains available for another caller
    When the other caller starts an authorized read
    Then the other caller's read is admitted
    And the first caller receives no additional capacity

  Scenario: Overload is explicit and retryable
    Given the configured read capacity is full
    When another authorized read cannot be admitted within the waiting bound
    Then it receives the documented retryable overload response
    And active reads continue without corruption

  Scenario: Compatible peers select the efficient transport
    Given the Server and Node support the same efficient transport version
    When an authorized caller reads a file
    Then the peers select that transport explicitly
    And the destination is byte-identical to the source

  Scenario: Incompatible peers refuse before transferring content
    Given the Server and Node have no common file transport version
    When an authorized caller reads a file
    Then the operation is refused with upgrade guidance
    And no file content is transferred

  Scenario: Required efficient transport never silently downgrades
    Given the efficient transport is required
    And the peer supports only an older transport
    When an authorized caller reads a file
    Then the operation is refused
    And authentication, replay protection, and path enforcement are not weakened
