@bdd @noninteractive
Feature: Fixed context summarization thresholds
  As an operator using fixed fallback thresholds
  I want each context layer to trigger deterministically
  So that context summarization remains predictable

  Scenario Outline: User2Agent quantity threshold is inclusive
    Given a deterministic summarize threshold harness
    And the User2Agent quantity threshold is 20 messages
    And User2Agent contains <count> messages
    When User2Agent summary need is evaluated
    Then User2Agent summarization is <needed>

    Examples:
      | count | needed     |
      | 19    | not needed |
      | 20    | needed     |
      | 21    | needed     |

  Scenario Outline: Agent2LLM quantity threshold is inclusive
    Given a deterministic summarize threshold harness
    And the Agent2LLM quantity threshold is 30 messages
    And Agent2LLM contains <count> messages
    When Agent2LLM summary need is evaluated
    Then Agent2LLM summarization is <needed>

    Examples:
      | count | needed     |
      | 29    | not needed |
      | 30    | needed     |
      | 31    | needed     |

  Scenario: A layer-specific quantity threshold overrides the shared threshold
    Given a deterministic summarize threshold harness
    And the User2Agent quantity threshold is 35 messages
    And the shared quantity threshold is 10 messages
    And User2Agent contains 20 messages
    When User2Agent summary need is evaluated
    Then User2Agent summarization is not needed

  Scenario: An unset layer threshold falls back to the shared threshold
    Given a deterministic summarize threshold harness
    And the Agent2LLM quantity threshold is unset
    And the shared quantity threshold is 23 messages
    And Agent2LLM contains 23 messages
    When Agent2LLM summary need is evaluated
    Then Agent2LLM summarization is needed

  Scenario Outline: Non-positive quantity configuration disables its trigger
    Given a deterministic summarize threshold harness
    And both layer and shared quantity thresholds are <threshold>
    And both layers contain 100 messages
    When quantity summary need is evaluated
    Then quantity-based summarization is disabled

    Examples:
      | threshold |
      | 0         |
      | -1        |
      | null      |

  Scenario Outline: User2Agent token threshold is strictly exceeded
    Given a deterministic summarize threshold harness
    And the User2Agent token threshold is 1000 tokens
    And User2Agent token usage is <tokens> tokens
    When User2Agent summary need is evaluated
    Then User2Agent summarization is <needed>

    Examples:
      | tokens | needed     |
      | 999    | not needed |
      | 1000   | not needed |
      | 1001   | needed     |

  Scenario Outline: Agent2LLM token threshold is strictly exceeded
    Given a deterministic summarize threshold harness
    And the Agent2LLM token threshold is 1000 tokens
    And Agent2LLM token usage is <tokens> tokens
    When Agent2LLM summary need is evaluated
    Then Agent2LLM summarization is <needed>

    Examples:
      | tokens | needed     |
      | 999    | not needed |
      | 1000   | not needed |
      | 1001   | needed     |

  Scenario: Disabled token thresholds do not trigger summarization
    Given a deterministic summarize threshold harness
    And both layer token thresholds are 0
    And both layers use 100000 tokens
    When each layer summary need is evaluated
    Then neither layer is triggered by token usage


  Scenario Outline: Agent2LLM duplicate-tool-call threshold is strictly exceeded
    Given a deterministic summarize threshold harness
    And the Agent2LLM duplicate-tool-call threshold is <threshold>
    And the consecutive duplicate tool call count is <count>
    When Agent2LLM summary need is evaluated
    Then Agent2LLM summarization is <needed>

    Examples:
      | threshold | count | needed     |
      | 3         | 3     | not needed |
      | 3         | 4     | needed     |
      | 0         | 500   | not needed |

  Scenario: A zero layer threshold falls back to a positive shared threshold
    Given a deterministic summarize threshold harness
    And the User2Agent quantity threshold is 0 messages
    And the shared quantity threshold is 67 messages
    And User2Agent contains 68 messages
    When User2Agent summary need is evaluated
    Then User2Agent summarization is needed
