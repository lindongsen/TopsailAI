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
