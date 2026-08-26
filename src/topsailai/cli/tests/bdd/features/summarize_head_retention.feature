@bdd @noninteractive
Feature: Summarize head and message retention
  As an operator preserving important context
  I want summary reconstruction controls to retain the configured messages
  So that summarization does not lose task or session boundaries

  Background:
    Given a deterministic summarize structure harness

  Scenario Outline: The intrinsic head honors the first-task retention switch
    Given first-task retention is <switch>
    When the intrinsic summary head is resolved
    Then the intrinsic head contains <count> messages
    And the intrinsic head task is <task_retention>

    Examples:
      | switch | count | task_retention |
      | on     | 3     | retained       |
      | off    | 2     | omitted        |

  Scenario: Forced Agent2LLM summarization bypasses profitability but not hard feasibility
    When Agent2LLM profitability is evaluated with and without force
    Then ordinary summarization is rejected as not smaller
    And forced summarization bypasses the profitability guard
    But forced summarization still honors hard feasibility

  Scenario: Head and tail offsets survive Agent2LLM reconstruction
    Given session-message retention is off
    And the summary head offset is 2 messages
    And the summary tail offset is 1 message
    When Agent2LLM messages are reconstructed
    Then the configured head messages are retained
    And the configured tail messages are retained
    And the rebuilt context ends with the last User2Agent user message

  Scenario Outline: The session-message switch controls Agent2LLM reconstruction
    Given session-message retention is <switch>
    And the summary head offset is 0 messages
    And the summary tail offset is 0 messages
    When Agent2LLM messages are reconstructed
    Then session messages are <retention> in the rebuilt context

    Examples:
      | switch | retention |
      | on     | present   |
      | off    | absent    |
