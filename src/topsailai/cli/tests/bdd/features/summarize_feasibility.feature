@bdd @noninteractive
Feature: Summarize feasibility watermarks
  As a user near the model context limit
  I want summary feasibility checks to honor strict capacity boundaries
  So that feasible equality is preserved and only excess is rejected

  Background:
    Given a deterministic summarize watermark harness

  Scenario Outline: Summary input equality is feasible but excess is rejected
    Given a model context of 1000 tokens with a summary margin of 100 tokens
    And summary feasibility uses safety coefficient 1.0
    And summary input tokens are <input_tokens> and preserved tokens are 100
    And the summary token reserve is 0
    When summary feasibility is checked
    Then summary feasibility is <outcome>

    Examples:
      | input_tokens | outcome |
      | 900          | allowed |
      | 901          | rejected |

  Scenario: Preserved budget equality is feasible
    Given a model context of 1000 tokens with a summary margin of 100 tokens
    And summary feasibility uses safety coefficient 1.0
    And summary input tokens are 100 and preserved tokens are 900
    And the summary token reserve is 0
    When summary feasibility is checked
    Then summary feasibility is allowed
