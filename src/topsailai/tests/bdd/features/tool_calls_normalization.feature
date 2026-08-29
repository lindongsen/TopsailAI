Feature: Tool calls remain valid across persistence and request boundaries

  Scenario: Structured tool calls survive persistence and reach the provider as JSON objects
    Given a tool-calls normalization environment with a private mock LLM server
    And the tool-calls normalization session "bdd_tc_roundtrip" is seeded with a structured assistant tool call message and its tool result
    When the tool-calls normalization session "bdd_tc_roundtrip" continues the conversation with "continue the task"
    Then the tool-calls normalization mock server received exactly 1 completion requests
    And every tool calls array the tool-calls normalization mock server received is a JSON array of objects with id, type and function

  Scenario: Legacy native repr history replayed under non-native mode no longer breaks the provider
    Given a tool-calls normalization environment with a private mock LLM server
    And the tool-calls normalization session "bdd_tc_legacy" is seeded with legacy malformed repr tool calls and its tool result
    When the tool-calls normalization session "bdd_tc_legacy" continues the conversation with "continue the task"
    Then the tool-calls normalization conversation completes without a bad request error
    And the tool-calls normalization mock server received exactly 1 completion requests
    And the tool-calls normalization mock server received no malformed tool calls value
    And the tool-calls normalization mock server received no ownerless tool result message

  Scenario: Replacement before-chat hook cannot inject malformed tool calls into the wire payload
    Given a tool-calls normalization environment with a private mock LLM server
    And the tool-calls normalization replacement hook "bdd_inject_malformed" injects malformed tool calls
    When the tool-calls normalization session "bdd_tc_hook" continues the conversation with "continue the task"
    Then the tool-calls normalization mock server received exactly 1 completion requests
    And the tool-calls normalization mock server received no malformed tool calls value

  Scenario: Single legitimate tool call round trip completes end to end
    Given a tool-calls normalization environment with a private mock LLM server
    And the tool-calls normalization mock server replies with tool calls to "safe_tool"
    And the tool-calls normalization session "bdd_tc_single" is seeded with a structured assistant tool call message and its tool result
    When the tool-calls normalization session "bdd_tc_single" continues the conversation with "continue the task"
    Then the tool-calls normalization conversation completes without a bad request error
    And the tool-calls normalization mock server received exactly 2 completion requests
    And every tool calls array the tool-calls normalization mock server received is a JSON array of objects with id, type and function

  Scenario: Two legitimate tool calls round trip completes end to end
    Given a tool-calls normalization environment with a private mock LLM server
    And the tool-calls normalization mock server replies with tool calls to "safe_tool,other_tool"
    And the tool-calls normalization session "bdd_tc_multi" is seeded with a structured assistant tool call message and its tool result
    When the tool-calls normalization session "bdd_tc_multi" continues the conversation with "continue the task"
    Then the tool-calls normalization conversation completes without a bad request error
    And the tool-calls normalization mock server received exactly 2 completion requests
    And every tool calls array the tool-calls normalization mock server received is a JSON array of objects with id, type and function

  Scenario: Parallel tool calls flow completes end to end
    Given a tool-calls normalization environment with a private mock LLM server
    And the tool-calls normalization mock server replies with tool calls to "safe_tool,other_tool"
    And the tool-calls normalization parallel tool calls mode is enabled
    And the tool-calls normalization session "bdd_tc_parallel" is seeded with a structured assistant tool call message and its tool result
    When the tool-calls normalization session "bdd_tc_parallel" continues the conversation with "continue the task"
    Then the tool-calls normalization conversation completes without a bad request error
    And the tool-calls normalization mock server received exactly 2 completion requests
    And every tool calls array the tool-calls normalization mock server received is a JSON array of objects with id, type and function

  Scenario: Degradation warning is bounded and leaks nothing sensitive
    Given a tool-calls normalization environment with a private mock LLM server
    And the tool-calls normalization session "bdd_tc_logs" is seeded with legacy malformed repr tool calls and its tool result
    When the tool-calls normalization session "bdd_tc_logs" continues the conversation with "continue the task"
    Then the tool-calls normalization logs contain the degradation warning with only index and type
    And the tool-calls normalization logs contain no tool arguments or tool result sentinel

  Scenario: Legacy native history remains safe after summarization under non-native mode
    Given a tool-calls normalization environment with a private mock LLM server
    And the tool-calls normalization session "bdd_tc_summarize" is seeded with legacy malformed repr tool calls and its tool result
    When the tool-calls normalization Agent2LLM context is forced through real summarization before the conversation continues
    Then the tool-calls normalization summarization and continuation requests are both observed
    And the tool-calls normalization mock server received exactly 2 completion requests
    And the tool-calls normalization mock server received no malformed tool calls value
    And the tool-calls normalization mock server received no ownerless tool result message

  Scenario: Native framework-produced tool call remains safe after legacy persistence degradation
    Given a tool-calls normalization environment with a private mock LLM server
    When the native tool-calls incident is produced by the framework, degraded during persistence, and replayed
    Then the native incident assistant call and tool result were produced by the framework
    And the native incident requests all include native tool definitions
    And the tool-calls normalization mock server received exactly 3 completion requests
    And the tool-calls normalization mock server received no malformed tool calls value
    And the native incident mock server received no ownerless tool result message
