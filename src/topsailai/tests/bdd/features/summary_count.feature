Feature: Count successful context summaries
  The user sees summary activity per turn and retains cumulative session totals.

  Scenario Outline: Successful applications accumulate and skipped work does not
    Given a summary counter for <layer> with <policy> context using a private provider
    When two summaries are applied in successive work intervals
    Then the session and runtime both record two summaries
    And a skipped summary leaves the totals and provider requests unchanged

    Examples:
      | layer      | policy   |
      | user2agent | normal   |
      | agent2llm  | normal   |
      | user2agent | recovery |
      | agent2llm  | recovery |
