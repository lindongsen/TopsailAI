Feature: Summarize Hooks preserve business outcomes across provider and session boundaries
  As an application operator and user
  I want optional managed observers to report truthful layer-specific checkpoints
  So that summaries retain provider behavior and application-scoped availability

  # Legacy API acceptance only: retained typed owner startup dispositions.
  # Business scenarios below use direct entries without owner injection.
  Scenario Outline: Application startup exposes safe phase-one dispositions
    Given a private sse summarize Hooks user2agent application for <case>
    When the summarize Hooks acceptance path runs
    Then the provider and managed observers prove the approved summary outcome
    Examples:
      | case     |
      | startup  |
      | disabled |

  # Acceptance: all-None startup does not cache resources or poison later acquisition.
  Scenario: Unconfigured startup permits a later configured real summary
    Given a private sse summarize Hooks user2agent application for unconfigured
    When the summarize Hooks acceptance path runs
    Then the provider and managed observers prove the approved summary outcome

  # Acceptance: BG precedes the provider and AA follows full layer application/accounting.
  Scenario Outline: Real summaries observe only their own completed layer
    Given a private <transport> summarize Hooks <layer> application for success
    When the summarize Hooks acceptance path runs
    Then the provider and managed observers prove the approved summary outcome
    Examples:
      | layer      | transport |
      | user2agent | sse       |
      | agent2llm  | sse       |

  # Acceptance: provider failure emits EG only; original primary traceback survives.
  Scenario Outline: Real provider failures remain generation business errors
    Given a private sse summarize Hooks <layer> application for generation_failure
    When the summarize Hooks acceptance path runs
    Then the provider and managed observers prove the approved summary outcome
    Examples:
      | layer      |
      | user2agent |
      | agent2llm  |

  # Acceptance: real generation followed by failed application emits truthful EA, not AA.
  Scenario Outline: Post-generation failure reports possible partial application
    Given a private sse summarize Hooks <layer> application for application_failure
    When the summarize Hooks acceptance path runs
    Then the provider and managed observers prove the approved summary outcome
    Examples:
      | layer      |
      | user2agent |
      | agent2llm  |

  # Acceptance: normal skips never claim successful application or manufacture errors.
  Scenario Outline: Summary skips retain the original business state
    Given a private sse summarize Hooks <layer> application for <case>
    When the summarize Hooks acceptance path runs
    Then the provider and managed observers prove the approved summary outcome
    Examples:
      | layer      | case            |
      | user2agent | empty_input     |
      | agent2llm  | empty_input     |
      | user2agent | feasibility     |
      | agent2llm  | feasibility     |
      | user2agent | human_rejection |

  # Acceptance: configured observer failure stays report-only and cannot recurse into EG/EA.
  Scenario Outline: Managed observer failure cannot change a successful summary
    Given a private sse summarize Hooks <layer> application for observer_failure
    When the summarize Hooks acceptance path runs
    Then the provider and managed observers prove the approved summary outcome
    Examples:
      | layer      |
      | user2agent |
      | agent2llm  |

  # Acceptance: real AgentChat.run finalization does not close application-scoped resources.
  Scenario: A second session can summarize after the first session closes
    Given a private sse summarize Hooks agent2llm application for session
    When the summarize Hooks acceptance path runs
    Then the provider and managed observers prove the approved summary outcome
