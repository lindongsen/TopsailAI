Feature: provider conversation rendering
  A provider stores most message bodies as its own step record, so printing the
  stored body shows JSON to the operator instead of the text they wrote. The
  cluster unwraps that record in the adapter, because the record format is
  provider detail, and renders the result as readable blocks. Each body can also
  be bounded on request, and the bound must never change the reported counts.

  These scenarios drive the shipped binaries over a real WebSocket, because the
  rendering, the bound and the refusals are only observable in the terminal. A
  unit test proves the renderer and the flag parser separately; only this layer
  proves the two are wired together in the binary an operator runs.

  Scenario: a conversation renders as readable blocks
    Given a real cluster with a session holding a structured body
    When the messages command is run for that session
    Then every message is rendered as a separated block with a header
    And the reported counts are real measurements

  Scenario: a structured body is unwrapped instead of printed as JSON
    Given a real cluster with a session holding a structured body
    When the messages command is run for that session
    Then the body shows the step label and its text without the record keys

  Scenario: a character bound shortens a body without changing the counts
    Given a real cluster with a session holding a structured body
    When the messages command is run with a character bound
    Then the body is shortened and the header counts are unchanged

  Scenario: a token bound shortens a body without changing the counts
    Given a real cluster with a session holding a structured body
    When the messages command is run with a token bound
    Then the body is shortened and the header counts are unchanged

  Scenario: a bound above the maximum is refused
    Given a real cluster with a session holding a structured body
    When the messages command is run with a bound above the maximum
    Then the command is refused and names the maximum

  Scenario: a negative bound is refused
    Given a real cluster with a session holding a structured body
    When the messages command is run with a negative bound
    Then the command is refused and names the value as negative

  Scenario: two disagreeing spellings are refused
    Given a real cluster with a session holding a structured body
    When the messages command is run with two disagreeing spellings
    Then the command is refused and asks for one bound
