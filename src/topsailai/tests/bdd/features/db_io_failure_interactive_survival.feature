Feature: Survive a database write failure without losing the session
  As an operator running an agent session
  I want a failed database write to abandon only the affected turn
  So that an interactive session stays usable and a non-interactive run never
  reports a lost write as success

  Scenario: An interactive session keeps waiting for the next message
    Given an interactive agent session whose database write fails
    When the turn is abandoned
    Then the session returns to the input prompt
    And the process is still alive
    And the session metadata is retained

  Scenario: An interactive session survives consecutive write failures
    Given an interactive agent session whose database write fails
    When 3 consecutive turns fail to persist
    Then the session returns to the input prompt after every failure
    And the process is still alive
    And the session metadata is retained

  Scenario: A non-interactive run exits non-zero instead of reporting success
    Given a non-interactive agent session whose database write fails
    When the turn is abandoned
    Then the run reports an explicit failure answer
    And the process exits with a non-zero code
    And the session metadata is left untouched
    And the stdout artifact keeps the failure evidence

  Scenario: A worker thread abandons only its own turn
    Given an interactive agent session whose database write fails in a worker thread
    When the turn is abandoned in a worker thread
    Then the worker thread does not terminate the process
    And the session metadata is retained
