Feature: History replay ignores evolving storage metadata
  Scenario: Two-turn persist mode ignores new storage metadata
    Given a real two-turn persist metadata scenario
    When the Agent completes both turns
    Then persisted metadata reaches the second merge and history remains exact

  Scenario: Two-turn native persist mode preserves tool pairing
    Given a real two-turn native persist metadata scenario
    When the Agent completes both turns
    Then native pairing remains exact after metadata replay
