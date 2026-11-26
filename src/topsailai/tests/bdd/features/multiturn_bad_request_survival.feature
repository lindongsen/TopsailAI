Feature: Survive a provider bad-request failure in a multi-turn session
  As an operator running an interactive agent session
  I want a provider bad-request failure to abandon only the current turn
  So that a multi-turn conversation keeps its runtime scene instead of the
  process terminating

  Scenario: A multi-turn interactive session abandons the turn
    Given an interactive multi-turn agent session whose provider rejects the request
    When the turn is abandoned
    Then the session returns to the input prompt
    And the process is still alive
    And the session metadata is retained

  Scenario: A multi-turn interactive session survives consecutive rejections
    Given an interactive multi-turn agent session whose provider rejects the request
    When 3 consecutive turns are rejected
    Then the session returns to the input prompt after every rejection
    And the process is still alive

  Scenario: A multi-turn session abandons the turn after retry exhaustion
    Given an interactive multi-turn agent session whose retries are exhausted by a rejection
    When the turn is abandoned
    Then the session returns to the input prompt
    And the process is still alive

  Scenario: A single-turn run keeps the rejection fatal
    Given a single-turn agent session whose provider rejects the request
    When the turn is abandoned
    Then the rejection stays fatal

  Scenario: A non-interactive multi-turn run keeps the rejection fatal
    Given a non-interactive multi-turn agent session whose provider rejects the request
    When the turn is abandoned
    Then the rejection stays fatal

  Scenario: A worker thread keeps the rejection fatal
    Given an interactive multi-turn agent session whose provider rejects the request in a worker thread
    When the turn is abandoned in a worker thread
    Then the rejection stays fatal

  Scenario: A permission-denied failure stays fatal in a multi-turn session
    Given an interactive multi-turn agent session whose provider denies permission
    When the turn is abandoned
    Then the rejection stays fatal
