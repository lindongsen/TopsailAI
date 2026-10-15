Feature: Warning-only first-byte continuity over the production loopback boundary

  Scenario: Warning mode continues delayed streaming headers
    Given a production U4 server with warning-only delayed streaming headers
    When the U4 streaming completion is consumed
    Then the U4 original stream is complete with one request and one warning

  Scenario: Warning mode continues a delayed first decoded entry
    Given a production U4 server with warning-only delayed first entry
    When the U4 streaming completion is consumed
    Then the U4 original stream is complete with one request and one warning

  Scenario: Warning mode continues cumulative delay with one shared warning
    Given a production U4 server with warning-only cumulative delay
    When the U4 streaming completion is consumed
    Then the U4 original stream is complete with one request and one warning

  Scenario: Warning mode on-time control has no warning
    Given a production U4 server with warning-only on-time streaming
    When the U4 streaming completion is consumed
    Then the U4 original stream is complete with one request and no warning

  Scenario: Warning creation and first entry share one budget
    Given a production U4 server with warning-only cross-phase delay
    When the U4 streaming completion is consumed
    Then the U4 cross-phase stream has one shared warning

  Scenario: Warning precedes a genuine provider error and existing retry
    Given a production U4 server with warning-only provider error then recovery
    When the U4 streaming completion is consumed
    Then the U4 recovered stream has two identical requests and one warning
