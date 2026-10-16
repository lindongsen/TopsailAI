Feature: Optional summary Scripts preserve user history and provider behavior
  As a user of an application with direct Hook Point observers
  I want Scripts to observe truthful summary checkpoints without changing my summary
  So that both conversation layers retain their normal results and failures

  # Acceptance: direct Modules and executable Scripts run with real HTTP/SSE.
  # stale now verifies discovery of membership added after configuration, not trust rejection.
  Scenario Outline: Direct observers preserve summary application
    Given a private <transport> mixed summary <layer> application using <mode> for <case>
    When the mixed summary acceptance path runs
    Then mixed observers and the real provider prove the unchanged business outcome
    Examples:
      | layer      | transport | mode    | case           |
      | user2agent | sse       | runtime | success        |
      | agent2llm  | sse       | runtime | success        |
      | user2agent | sse       | message | success        |
      | agent2llm  | sse       | message | success        |
      | user2agent | sse       | runtime | script_failure |
      | agent2llm  | sse       | runtime | script_failure |
      | user2agent | sse       | runtime | stale          |
      | user2agent | sse       | runtime | session        |

  # Acceptance: skips never pretend that history was applied.
  Scenario Outline: Unapplied summaries produce no false success
    Given a private sse mixed summary <layer> application using runtime for <case>
    When the mixed summary acceptance path runs
    Then mixed observers and the real provider prove the unchanged business outcome
    Examples:
      | layer      | case            |
      | user2agent | empty_input     |
      | agent2llm  | empty_input     |
      | user2agent | feasibility     |
      | agent2llm  | feasibility     |
      | user2agent | human_rejection |

  # Acceptance: business exception identity wins over failed error observers.
  Scenario Outline: Business failures retain truthful checkpoints
    Given a private sse mixed summary <layer> application using runtime for <case>
    When the mixed summary acceptance path runs
    Then mixed observers and the real provider prove the unchanged business outcome
    Examples:
      | layer      | case                |
      | user2agent | generation_failure  |
      | agent2llm  | generation_failure  |
      | user2agent | application_failure |
      | agent2llm  | application_failure |

  # Acceptance: real empty SSE responses exhaust validation retries, not owner skips.
  Scenario Outline: Empty provider responses retain retry exhaustion
    Given a private sse mixed summary <layer> application using runtime for empty_provider_exhaustion
    When the mixed summary acceptance path runs
    Then mixed observers and the real provider prove the unchanged business outcome
    Examples:
      | layer      |
      | user2agent |
      | agent2llm  |
