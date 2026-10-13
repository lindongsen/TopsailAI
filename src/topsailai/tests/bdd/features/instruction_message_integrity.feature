Feature: Instruction views preserve ordered Agent messages
  Scenario: A completed turn is visible through instructions and the mock server
    Given a fresh Agent integrity scenario with naming disabled
    When the Agent completes one real turn and the operator inspects messages
    Then the instruction reports and mock request preserve the expected order

  Scenario: Instruction inspection is pure after a completed turn
    Given a fresh Agent integrity scenario with naming disabled
    When the Agent completes one real turn and the operator inspects messages
    Then the instruction reports and mock request preserve the expected order

  Scenario: Same session preserves ordered messages in reset mode
    Given a fresh two-turn Agent integrity scenario in reset mode
    When the Agent completes two real turns on the configured session
    Then both turn reports preserve the expected order without duplicate injection

  Scenario: Same session preserves ordered messages in persist mode
    Given a fresh two-turn Agent integrity scenario in persist mode
    When the Agent completes two real turns on the configured session
    Then both turn reports preserve the expected order without duplicate injection

  Scenario: Rebuilt Agent restores the same session without rereading USER.md
    Given a fresh rebuilt-Agent integrity scenario
    When the Agent completes two real turns using rebuilt instances
    Then the rebuilt Agent preserves history and cache identity
