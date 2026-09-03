@bdd @noninteractive
Feature: llm_mock_server streaming support over real HTTP/SSE
  As a developer relying on the mock LLM server
  I want streaming chunks, usage accounting, and error paths served over real HTTP/SSE
  So that the production streaming chain consumes them exactly like a real provider

  Background:
    Given a streaming LLM mock server with SSE chunks

  Scenario: Streaming response exposes explicit usage after all response chunks
    Given the SSE chunks are "Hello ", "streaming ", "world"
    When the streaming mock chat is executed
    Then the streamed content equals "Hello streaming world"
    And the stream produced first-byte timing on the token stat
    And the mock server receives exactly one usage-enabled streaming request
    And the streaming request contains the scenario user message
    And the streaming token stat exposes prompt completion and combined totals
    And the legacy streaming token fields remain prompt-only
    And session CLI token fields distinguish prompt completion and combined usage
    And every streamed response chunk is output before the token summary

  Scenario: Missing Provider usage falls back to completion text estimation
    Given a streaming LLM mock server that omits usage
    And the SSE chunks are "local ", "completion ", "estimate"
    When the streaming mock chat is executed
    Then completion tokens equal the local estimate of "local completion estimate"
    And the mock server receives exactly one usage-enabled streaming request

  Scenario: Streaming usage chunk feeds cached tokens into TokenStat
    Given the SSE chunks are "alpha", "beta"
    When the streaming mock chat is executed twice with the same prompt
    Then the second server-side request reports cached tokens greater than zero
    And the token stat current cached tokens equal the server-reported value
    And the token stat total cached tokens accumulate both requests

  Scenario: Stream request against streaming-disabled server surfaces a bad request error
    Given a streaming LLM mock server with streaming disabled
    When the streaming mock chat is executed directly without the retry loop
    Then a bad request error surfaces with "streaming is not supported"
    And the mock server receives exactly one streaming-disabled request

  Scenario: Stream terminates cleanly at DONE sentinel with accurate request accounting
    Given the SSE chunks are "done ", "check"
    When the streaming mock chat is executed twice with different prompts
    Then the streamed content equals "done check" on the first call
    And the mock server state reports exactly two total requests
    And each recorded request has a positive prompt token count
