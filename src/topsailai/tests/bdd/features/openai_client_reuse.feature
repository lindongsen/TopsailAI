Feature: OpenAI SDK client reuse across LLM runtimes
  As an operator
  I want Agent2LLM and runtime context summarization to reuse one SDK client
  So that identical provider configuration does not create duplicate transports

  Scenario: Runtime summarization reuses the Agent2LLM OpenAI SDK client
    Given an OpenAI client reuse environment with a private mock LLM server
    When Agent2LLM and runtime summarization each send one real LLM request
    Then the OpenAI client reuse mock server received exactly 2 completion requests
    And the Agent2LLM and summary request bodies reached the mock server
    And runtime summarization uses a distinct OpenAI client lease
    But runtime summarization reuses the Agent2LLM root OpenAI SDK client instance
    And runtime summarization reuses the Agent2LLM chat completions instance
