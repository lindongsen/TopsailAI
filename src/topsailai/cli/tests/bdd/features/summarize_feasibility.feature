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


  Scenario Outline: Dynamic feasibility reports the hard rejection reason
    Given a model context of 1000 tokens with a summary margin of 100 tokens
    And summary feasibility uses safety coefficient 1.0
    And summary input tokens are <input_tokens> and preserved tokens are <preserved_tokens>
    And the summary token reserve is 0
    When summary feasibility is checked
    Then summary feasibility is rejected with reason <reason>

    Examples:
      | input_tokens | preserved_tokens | reason                               |
      | 1001         | 100              | summary_input_exceeds_model_context  |
      | 901          | 100              | summary_input_exceeds_safe_limit     |
      | 100          | 901              | preserved_budget_exceeds_safe_limit  |

  Scenario Outline: Summary reserve accounting can change feasibility
    Given a model context of 5000 tokens with a summary margin of 800 tokens
    And summary feasibility uses safety coefficient 1.0
    And summary input tokens are 100 and preserved tokens are 100
    And the summary token reserve is <reserve>
    When summary feasibility is checked
    Then summary feasibility is <outcome>

    Examples:
      | reserve | outcome  |
      | 4080    | allowed  |
      | 4120    | rejected |
