Feature: Recorded events reach the on-disk events file
  As an operator
  I want the events file written by the production file backend to contain the
  real event sources
  So that I can audit what the agent actually did without attaching a subscriber

  Scenario: A successful LLM request writes a paired start and end record
    Given an events file owned by this scenario
    When a real LLM request completes successfully
    Then the events file holds exactly one "llm.request.start" record
    And the events file holds exactly one "llm.request.end" record
    And both LLM request records share one operation id
    And the LLM request end record reports outcome "success"

  Scenario: An interrupted LLM request writes an interrupted terminal record
    Given an events file owned by this scenario
    When a real LLM request is stopped by "HardInterruptError"
    Then the events file holds exactly one "llm.request.start" record
    And the events file holds exactly one "llm.request.end" record
    And both LLM request records share one operation id
    And the LLM request end record reports outcome "interrupted"
    And the LLM request end record reports error category "HardInterruptError"
    And the LLM request end record reports zero attempts

  Scenario: A keyboard interrupt writes an interrupted terminal record
    Given an events file owned by this scenario
    When a real LLM request is stopped by "KeyboardInterrupt"
    Then the events file holds exactly one "llm.request.start" record
    And the events file holds exactly one "llm.request.end" record
    And the LLM request end record reports outcome "interrupted"
    And the LLM request end record reports error category "KeyboardInterrupt"

  Scenario: A tool call writes paired start and end records
    Given an events file owned by this scenario
    When a real tool call executes successfully
    Then the events file holds exactly one "tool_call.start" record
    And the events file holds exactly one "tool_call.end" record
    And the tool call end record reports success

  Scenario: An approval decision writes paired records sharing one instance id
    Given an events file owned by this scenario
    When a real approval request is approved by the human
    Then the events file holds exactly one "tool_approval.request" record
    And the events file holds exactly one "tool_approval.decision" record
    And both approval records share one instance id
    And the approval decision record reports status "approved"

  Scenario: Operational records never carry prompt text or approval arguments
    Given an events file owned by this scenario
    When a real LLM request completes successfully
    And a real approval request is approved by the human
    Then no LLM request record contains the prompt text
    And no approval record contains the tool argument

  Scenario: Disabling events writes no events file
    Given an events file owned by this scenario with events disabled
    When a real LLM request completes successfully
    Then no events file was written

  Scenario: A raw LLM response writes a response record
    Given an events file owned by this scenario with raw response events enabled
    When a real LLM request completes successfully
    Then the events file holds exactly one "llm.response.raw" record
    And the raw response record reports the reply content
    And the raw response record omits the raw provider object

  Scenario: A repeated tool call writes a warning record
    Given an events file owned by this scenario with a repeated tool-call warning rule
    When the same real tool call executes twice
    Then the events file holds exactly one "tool_call.warning" record
    And the tool-call warning record reports the tool name and count

  Scenario: An abnormal thought writes a line-pattern warning record
    Given an events file owned by this scenario with thought line-pattern detection enabled
    When a real thought evaluation matches the configured pattern
    Then the events file holds exactly one "thought.line_pattern.warning" record
    And the thought warning record reports the matched pattern

  Scenario: A real summary cycle writes summary hook observations
    Given an events file owned by this scenario with summary observation enabled
    When a real summary cycle completes
    Then the events file holds exactly two "summary.hook.observed" records
    And the summary observation records report the before and success outcomes
    And the summary observation records share one operation id
    And the summary observation records come from the summary observer
    And the summary observation payload carries only metadata

  Scenario: Disabling events writes no summary observation
    Given an events file owned by this scenario with summary observation enabled but events disabled
    When a real summary cycle completes
    Then no events file was written
