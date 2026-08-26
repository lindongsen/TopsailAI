@bdd @noninteractive
Feature: Summarize session retention controls
  As a user running a long session
  I want session retention thresholds to be deterministic
  So that summaries preserve useful context without exceeding the budget

  Background:
    Given a deterministic summarize watermark harness

  Scenario Outline: Session maximum ratio controls retention at its inclusive boundary
    Given the Agent2LLM quantity threshold is 100 messages
    And the session maximum ratio is <ratio>
    And Agent2LLM has 60 messages and User2Agent has <session_count> messages
    When Agent2LLM session retention is evaluated
    Then session messages are <retention>

    Examples:
      | ratio | session_count | retention |
      | 0.5   | 49            | kept      |
      | 0.5   | 50            | dropped   |
      | 0.5   | 51            | dropped   |
      | NaN   | 10            | kept      |

  Scenario Outline: Invalid minimum extra message values fall back to 17
    Given the session maximum ratio is 1.0
    And Agent2LLM has <agent_count> messages and User2Agent has <session_count> messages
    And the minimum extra message setting is <minimum>
    When minimum-extra summarization is evaluated without force
    Then minimum-extra summarization is <outcome>

    Examples:
      | agent_count | session_count | minimum | outcome |
      | 10          | 10            | -3      | skipped |
      | 27          | 10            | -3      | summarized |

  Scenario: Minimum-extra guard can be bypassed by forced summarization
    Given the session maximum ratio is 1.0
    And Agent2LLM has 10 messages and User2Agent has 10 messages
    And the minimum extra message setting is 17
    When minimum-extra summarization is evaluated with force
    Then minimum-extra summarization is summarized
