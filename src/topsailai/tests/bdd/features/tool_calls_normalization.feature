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


  Scenario: Tool result messages without usable call ids are removed at the request boundary
    Given a tool-calls normalization environment with a private mock LLM server
    And the tool-calls normalization session "bdd_tc_missing_ids" is seeded with tool result messages whose call ids are absent or blank
    When the tool-calls normalization session "bdd_tc_missing_ids" continues the conversation with "continue the task"
    Then the tool-calls normalization conversation completes without a bad request error
    And the tool-calls normalization mock server received exactly 1 completion requests
    And the tool-calls normalization mock server received no tool result message with an absent or blank call id

  Scenario: Non-native mode still sanitizes inherited native tool data at the request boundary
    Given a tool-calls normalization environment with a private mock LLM server
    And the non-native tool-calls mode skips both mode-gated earlier cleanup sites
    And the tool-calls normalization session "bdd_tc_nonnative_inherited" is seeded with one paired native tool result and two unowned tool results
    When the tool-calls normalization session "bdd_tc_nonnative_inherited" continues the conversation with "continue the task"
    Then the tool-calls normalization conversation completes without a bad request error
    And the tool-calls normalization mock server received exactly 1 completion requests
    And the non-native request boundary drops the unowned tool results and keeps the paired result
    And the tool-calls normalization mock server received no tool result message with an absent or blank call id

  Scenario: Pure non-native conversation passes the request boundary without any tool construct
    Given a tool-calls normalization environment with a private mock LLM server
    And the tool-calls normalization session "bdd_tc_nonnative_plain" is seeded with ordinary non-native conversation messages
    When the tool-calls normalization session "bdd_tc_nonnative_plain" continues the conversation with "continue the task"
    Then the tool-calls normalization mock server received exactly 1 completion requests
    And the non-native wire request carries no tool calls array and no tool result message
    And the non-native ordinary conversation reaches the provider unchanged and in order

  Scenario: Non-native textual ReAct observation survives the request boundary as an ordinary message
    Given a tool-calls normalization environment with a private mock LLM server
    And the tool-calls normalization session "bdd_tc_nonnative_observation" is seeded with ordinary non-native conversation messages
    When the tool-calls normalization session "bdd_tc_nonnative_observation" continues the conversation with "continue the task"
    Then the non-native textual observation reaches the provider as a user message with its observation step
    And the non-native wire request carries no tool calls array and no tool result message

  Scenario: Mixed thought final answer and native tool call executes before the turn ends
    Given a tool-calls normalization environment with a private mock LLM server
    And the tool-calls normalization mock server replies with thought final answer and a native tool call
    When the tool-calls normalization session "bdd_tc_mixed_final" continues the conversation with "request approval"
    Then the tool-calls normalization conversation completes without a bad request error
    And the tool-calls normalization mock server received exactly 2 completion requests
    And the mixed native response executes its tool before the final answer can end the turn

  Scenario: Existing action with a native tool call executes without duplication
    Given a tool-calls normalization environment with a private mock LLM server
    And the tool-calls normalization mock server replies with action final answer and a native tool call
    When the tool-calls normalization session "bdd_tc_existing_native_action" continues the conversation with "run the existing action"
    Then the tool-calls normalization conversation completes without a bad request error
    And the tool-calls normalization mock server received exactly 2 completion requests
    And the existing action is preserved once while its premature final becomes thought
    And the existing native action produces one paired tool result before completion

  Scenario: Existing action without a native tool call remains unchanged
    Given a tool-calls normalization environment with a private mock LLM server
    And the tool-calls normalization mock server replies with an action and no native tool call
    When the tool-calls normalization session "bdd_tc_existing_plain_action" continues the conversation with "preserve the existing action"
    Then the tool-calls normalization mock server received exactly 1 completion requests
    And the action response without a native tool call remains unchanged
    And no native final conversion warning is emitted

  Scenario: Unexecuted human decision call is preserved as thought at the request boundary
    Given a tool-calls normalization environment with a private mock LLM server
    And the tool-calls normalization session "bdd_tc_human_dangling" is seeded with an unexecuted human decision call
    When the tool-calls normalization session "bdd_tc_human_dangling" continues the conversation with "continue without the decision output"
    Then the tool-calls normalization conversation completes without a bad request error
    And the tool-calls normalization mock server received exactly 1 completion requests
    And the dangling human decision reaches the provider as thought instead of a native tool call

  Scenario: Model switching sanitizes dangling native history without discarding it
    Given a tool-calls normalization environment with a private mock LLM server
    And the tool-calls normalization session "bdd_tc_model_switch" is seeded with an unexecuted human decision call
    When the tool-calls normalization session "bdd_tc_model_switch" continues with model "mock-model-after-switch"
    Then the tool-calls normalization conversation completes without a bad request error
    And the tool-calls normalization mock server received exactly 1 completion requests
    And the selected tool-calls normalization model "mock-model-after-switch" reached the provider
    And the dangling human decision reaches the provider as thought instead of a native tool call

  Scenario: Session recovery sanitizes persisted dangling native history without discarding it
    Given a tool-calls normalization environment with a private mock LLM server
    And the tool-calls normalization session "bdd_tc_session_recovery" is seeded with an unexecuted human decision call
    When the tool-calls normalization session "bdd_tc_session_recovery" is recovered and continues
    Then the tool-calls normalization conversation completes without a bad request error
    And the tool-calls normalization mock server received exactly 1 completion requests
    And the dangling human decision reaches the provider as thought instead of a native tool call
