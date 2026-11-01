Feature: command idempotency
  Scenario: repeating the same command id and intent is idempotent
    Given an isolated Agent Cluster server
    When the same command "command-1" is submitted twice with the same intent
    Then both command submissions are accepted
    And command "command-1" has one durable record

  Scenario: changing an intent with the same command id is a conflict
    Given an isolated Agent Cluster server
    When command "command-2" is submitted with payload "first"
    And command "command-2" is submitted with payload "second"
    Then the second command submission is an intent conflict