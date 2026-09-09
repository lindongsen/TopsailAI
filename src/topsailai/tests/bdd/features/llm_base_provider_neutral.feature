Feature: LLM base import is provider-neutral
  As an operator
  I want importing the LLM base module to not load the OpenAI SDK
  So that provider-neutral code paths stay free of OpenAI SDK dependencies

  Scenario: Importing llm_base does not load the OpenAI SDK
    Given a clean Python subprocess
    When the subprocess imports ai_base.llm_base
    Then the OpenAI SDK is not loaded
    And the httpx transport is not loaded
    And the httpcore transport is not loaded

  Scenario: Instantiating LLMModel loads the OpenAI backend on demand
    Given a clean Python subprocess
    When the subprocess imports ai_base.llm_base and instantiates LLMModel
    Then the OpenAI backend resolves to the openai provider
    And the OpenAI SDK is loaded only after instantiation
