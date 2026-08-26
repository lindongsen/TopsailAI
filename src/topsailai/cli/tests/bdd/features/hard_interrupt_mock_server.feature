@bdd @noninteractive
Feature: Hard interrupt bypasses LLM retry over HTTP streaming
  As a user stopping a running agent through the Control Channel
  I want a hard interrupt observed during a real HTTP stream to bypass LLM retry
  So that the interrupted provider request is never repeated

  Background:
    Given a hard-interrupt LLM mock server with SSE streaming

  Scenario Outline: HTTP streaming hard interrupt never prompts or retries
    Given the HTTP retry prompt would be answered <answer>
    And a hard interrupt will surface after an HTTP SSE chunk
    When the HTTP streaming chat is executed
    Then the HTTP hard interrupt propagates immediately
    And no HTTP LLM retry prompt is shown
    And the mock server receives exactly one completion request

    Examples:
      | answer |
      | yes    |
      | no     |

  Scenario: Retry-loop hard interrupt stops after one HTTP streaming request
    Given an HTTP streaming request will end with a retryable client failure
    And a hard interrupt will surface at the next HTTP retry-loop check
    When the HTTP streaming chat is executed
    Then the HTTP hard interrupt propagates immediately
    And no HTTP LLM retry prompt is shown
    And the mock server receives exactly one completion request
