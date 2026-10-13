Feature: Instruction views preserve ordered Agent messages
  Scenario: A completed turn is visible through instructions and the mock server
    Given a fresh Agent integrity scenario with naming disabled
    When the Agent completes one real turn and the operator inspects messages
    Then the instruction reports and mock request preserve the expected order

  Scenario: Instruction inspection is pure after a completed turn
    Given a fresh Agent integrity scenario with naming disabled
    When the Agent completes one real turn and the operator inspects messages
    Then the instruction reports and mock request preserve the expected order
