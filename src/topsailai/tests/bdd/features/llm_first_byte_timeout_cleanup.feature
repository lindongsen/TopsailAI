Feature: Superseded first-byte attempts release their responses
  As an LLM client
  I want timed-out attempts to be discarded and closed
  So retries do not leak transport resources or publish stale content

  Scenario Outline: A superseded attempt is discarded and its response is released
    Given a real first-byte ownership server delays request 1 in the <phase> phase
    When the production streaming chat retries after the first-byte timeout
    Then request 2 succeeds with FRESH_SECOND and exactly two request bodies were captured
    And a mismatched request body is rejected
    And stale content is absent from senders usage and response events
    When request 1 is released
    Then the old response is closed and its exact handler thread exits
    And stale content remains absent after settlement

    Examples:
      | phase      |
      | headers    |
      | first_item |

  Scenario Outline: Closing an abandoned response preserves a sibling on the same pool
    Given a real shared-pool ownership server delays request 1 and request 3 in the <phase> phase
    When the retry and an in-flight sibling request use the same pooled client
    Then request 2 succeeds while request 3 remains in flight
    When request 1 is released while request 3 remains held
    Then the old response is closed while the sibling remains held
    When a follow-up request runs while request 3 remains held
    Then the follow-up succeeds without closing the shared root client
    When request 3 is released
    Then the sibling succeeds and exact client workers settle

    Examples:
      | phase      |
      | headers    |
      | first_item |
