@bdd @noninteractive
Feature: Hard interrupt bypasses LLM retry
  As a user stopping a running agent through the Control Channel
  I want the hard interrupt to bypass LLM retry handling
  So that the interrupted request stops immediately

  Background:
    Given a deterministic hard-interrupt LLM harness

  Scenario Outline: Streaming hard interrupt never prompts or retries
    Given the retry prompt would be answered <answer>
    And a hard interrupt will surface during LLM streaming
    When the streaming chat is executed
    Then the hard interrupt propagates immediately
    And no LLM retry prompt is shown
    And exactly one LLM request is issued

    Examples:
      | answer |
      | yes    |
      | no     |

  Scenario: Retry-loop hard interrupt stops before another request
    Given a retryable LLM failure has occurred
    And a hard interrupt will surface at the next retry-loop check
    When the non-streaming chat is executed
    Then the hard interrupt propagates immediately
    And no LLM retry prompt is shown
    And exactly one LLM request is issued
