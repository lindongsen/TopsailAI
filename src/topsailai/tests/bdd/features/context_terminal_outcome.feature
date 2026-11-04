Feature: Context protection communicates failure honestly
  As an agent operator
  I want an unrecoverable context limit to be reported as an error
  So that a terminated task is not mistaken for completed work

  Scenario: A locally rejected turn retains its termination reason
    Given a session whose agent is rejected by context protection
    When the session runs the rejected turn
    Then the session metadata records error rather than completed
    And the termination reason is displayed and saved once
    And no completion hooks run for the rejected turn
