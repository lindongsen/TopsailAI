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

  Scenario: React automatic naming preserves startup and business message boundaries
    Given a fresh react Agent integrity naming scenario
    When the Agent completes the naming scenario turns
    Then naming traffic is isolated and business messages remain ordered

  Scenario: Plan automatic naming preserves startup and business message boundaries
    Given a fresh plan Agent integrity naming scenario
    When the Agent completes the naming scenario turns
    Then naming traffic is isolated and business messages remain ordered

  Scenario: Disabled USER.md preserves explicit startup context
    Given a fresh disabled USER.md Agent integrity scenario
    When the Agent completes the disabled USER.md turn
    Then explicit startup context remains and USER.md is absent

  Scenario: Tool prompt remains system-only across turns
    Given a fresh tool-prompt Agent integrity scenario
    When the Agent completes the tool-prompt turns
    Then the tool marker remains system-only and is not persisted

  Scenario: History slice is an exact non-mutating view
    Given a fresh history-slice Agent integrity scenario
    When the Agent completes the history-slice turns
    Then the history slice matches positions one through three without mutation
