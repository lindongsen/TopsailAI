Feature: Pause the agent loop through the control channel
  As an operator
  I want to pause a running agent loop and decide whether it continues
  So that I can inspect or redirect the work without killing the session

  Scenario: A pause request blocks the loop and yes resumes it
    Given a pause control server with session "bdd-pause"
    When the operator requests pause twice and answers yes
    Then the loop resumes after exactly one consumed marker

  Scenario: Answering no interrupts the loop without saving an answer
    Given a pause control server with session "bdd-pause"
    When the operator requests pause and answers no
    Then the loop is interrupted before any provider request

  Scenario: A hard interrupt ends a pause within one poll slice
    Given a pause control server with session "bdd-pause"
    When a hard interrupt arrives while the loop waits for an answer
    Then the pause ends within one poll slice and clears the pending marker

  Scenario: A pause without an input channel fails open
    Given a pause control server with session "bdd-pause"
    When the operator requests pause with no interactive input channel
    Then the loop continues with the default answer and logs a warning

  Scenario: A nested subagent does not consume the pause marker
    Given a pause control server with session "bdd-pause"
    When a nested agent reaches the pause checkpoint
    Then the marker survives for the outermost agent
