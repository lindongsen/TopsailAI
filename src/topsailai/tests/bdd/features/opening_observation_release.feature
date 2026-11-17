Feature: Release the opening observation after summarization
  As an agent operator
  I want an oversized startup observation to be released once a summary exists
  So that a large startup context cannot stay pinned in every later request


  Scenario: An oversized opening observation is released after the summary
    Given an opening observation release with ratio 0.3 and a token threshold of 1000
    And a large startup observation
    When the user-facing summarization completes
    Then the opening observation is gone from memory
    And the opening observation is gone from storage
    And the summary request reached the provider exactly once

  Scenario: A small opening observation stays pinned
    Given an opening observation release with ratio 0.3 and a token threshold of 1000
    And a small startup observation
    When the user-facing summarization completes
    Then the opening observation is still in memory
    And the opening observation is still in storage

  Scenario: A zero ratio disables the release
    Given an opening observation release with ratio 0 and a token threshold of 1000
    And a large startup observation
    When the user-facing summarization completes
    Then the opening observation is still in memory
    And the opening observation is still in storage

  Scenario: A skipped summarization never releases the observation
    Given an opening observation release with ratio 0.3 and a token threshold of 1000
    And a large startup observation
    When the user-facing summarization is skipped
    Then the opening observation is still in memory
    And the opening observation is still in storage
    And no release warning was printed
    And no release event was recorded

  Scenario: A later user-role tool observation survives the release
    Given an opening observation release with ratio 0.3 and a token threshold of 1000
    And a large startup observation
    And a later user-role tool observation
    When the user-facing summarization completes
    Then the startup observation is gone from storage
    And the later user-role tool observation is still in storage

  Scenario: The release prints a warning and records an event
    Given an opening observation release with ratio 0.3 and a token threshold of 1000
    And a large startup observation
    When the user-facing summarization completes
    Then a release warning names the removed count and the decision inputs
    And a release event records the decision inputs

  Scenario: The agent-layer summarization releases the observation from memory only
    Given an opening observation release with ratio 0.3 and a token threshold of 1000
    And a large startup observation
    When the agent-layer summarization completes
    Then the opening observation is gone from agent memory
    And the opening observation is still in storage
    And the summary request reached the provider exactly once

  Scenario: The in-memory branch releases the observation without a session
    Given an opening observation release with ratio 0.3 and a token threshold of 1000
    And a large startup observation
    When the user-facing summarization completes without a session
    Then the opening observation is gone from memory
    And the opening observation is still in storage
    And the summary request reached the provider exactly once

  # ------------------------------------------------------------------
  # Group A: persist-before-delete ordering, observed at call time.
  #
  # The ordering is NOT observable in the final state: both orders converge
  # on the same end result. It is only observable at the instant the release
  # is invoked, which is why these scenarios assert call-time state instead
  # of the surviving message list.
  # ------------------------------------------------------------------

  Scenario: With a session the summary is already persisted when the release runs
    Given an opening observation release with ratio 0.3 and a token threshold of 1000
    And a large startup observation
    When the user-facing summarization completes
    Then the summary was already persisted when the release ran
    And the release ran exactly once

  Scenario: With a session the release operates on the persisted reconstruction
    Given an opening observation release with ratio 0.3 and a token threshold of 1000
    And a large startup observation
    When the user-facing summarization completes
    Then the release did not operate on the in-memory session list
    And the release ran exactly once

  Scenario: Without a session the summary is already applied when the release runs
    Given an opening observation release with ratio 0.3 and a token threshold of 1000
    And a large startup observation
    When the user-facing summarization completes without a session
    Then the summary was already present in the released list when the release ran
    And the release ran exactly once

  Scenario: Without a session the release operates on the in-memory session list
    Given an opening observation release with ratio 0.3 and a token threshold of 1000
    And a large startup observation
    When the user-facing summarization completes without a session
    Then the release operated on the in-memory session list
    And the release ran exactly once

  Scenario: The agent layer releases a list that already contains the summary
    Given an opening observation release with ratio 0.3 and a token threshold of 1000
    And a large startup observation
    When the agent-layer summarization completes
    Then the summary was already present in the released list when the release ran
    And the release ran exactly once

  # ------------------------------------------------------------------
  # Group B: a failed summary write suppresses the deletion entirely.
  # ------------------------------------------------------------------

  Scenario: A failed summary write leaves the observation in storage
    Given an opening observation release with ratio 0.3 and a token threshold of 1000
    And a large startup observation
    And the summary write will fail
    When the user-facing summarization completes
    Then the opening observation is still in storage
    And the opening observation is still in memory

  Scenario: A failed summary write never invokes the release
    Given an opening observation release with ratio 0.3 and a token threshold of 1000
    And a large startup observation
    And the summary write will fail
    When the user-facing summarization completes
    Then the release was never invoked
    And no release warning was printed
    And no release event was recorded

  # ------------------------------------------------------------------
  # Group C: the ratio comparison is inclusive.
  #
  # The seeded block measures 304 tokens against a 1000-token budget, so
  # ratio 0.303 releases and ratio 0.304 pins. Only the pair proves the
  # comparison is ``<=`` and not ``<``.
  # ------------------------------------------------------------------

  Scenario: A block just above the ratio boundary is released
    Given an opening observation release with ratio 0.303 and a token threshold of 1000
    And a boundary startup observation
    When the user-facing summarization completes
    Then the opening observation is gone from memory
    And the opening observation is gone from storage

  Scenario: A block exactly at the ratio boundary stays pinned
    Given an opening observation release with ratio 0.304 and a token threshold of 1000
    And a boundary startup observation
    When the user-facing summarization completes
    Then the opening observation is still in memory
    And the opening observation is still in storage
    And no release warning was printed

  # ------------------------------------------------------------------
  # Group D: the built-in default and the invalid-value fallback.
  # ------------------------------------------------------------------

  Scenario: The default ratio releases a block above its threshold
    Given an opening observation release with the default ratio and a token threshold of 1000
    And a large startup observation
    When the user-facing summarization completes
    Then the opening observation is gone from memory
    And the opening observation is gone from storage
    And the release warning names the default ratio

  Scenario: The default ratio pins a block below its threshold
    Given an opening observation release with the default ratio and a token threshold of 1000
    And a mid-size startup observation
    When the user-facing summarization completes
    Then the opening observation is still in memory
    And the opening observation is still in storage
    And no release warning was printed

  Scenario: An out-of-range ratio falls back to the default and releases
    Given an opening observation release with ratio 1.5 and a token threshold of 1000
    And a large startup observation
    When the user-facing summarization completes
    Then the opening observation is gone from memory
    And the release warning names the default ratio

  Scenario: An out-of-range ratio falls back to the default and pins a small block
    Given an opening observation release with ratio 1.5 and a token threshold of 1000
    And a mid-size startup observation
    When the user-facing summarization completes
    Then the opening observation is still in memory
    And no release warning was printed

  # ------------------------------------------------------------------
  # Group E: the no-session path replaces the observation with the summary.
  # ------------------------------------------------------------------

  Scenario: Without a session the summary replaces the observation in the session list
    Given an opening observation release with ratio 0.3 and a token threshold of 1000
    And a large startup observation
    When the user-facing summarization completes without a session
    Then the opening observation is gone from memory
    And the summary is present in the in-memory session

  Scenario: Without a session no persisted row is deleted
    Given an opening observation release with ratio 0.3 and a token threshold of 1000
    And a large startup observation
    When the user-facing summarization completes without a session
    Then the opening observation is still in storage
    And the summary is not in storage
