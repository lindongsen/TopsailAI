Feature: Unified first-byte deadline over the production loopback boundary

  Scenario: Empty decoded stream entry is accepted before later delayed content
    Given a production U3 server with an empty first stream entry and delayed later content
    When the production streaming completion is consumed
    Then the empty entry is accepted and the complete streamed response is returned

  Scenario: Raising mode retries a delayed first stream entry
    Given a production U3 server with a delayed first stream entry and a fresh retry result
    When the production streaming completion is consumed
    Then the second attempt result is returned and exactly two bodies are captured

  Scenario: Raising mode retries a delayed complete response
    Given a production U3 server with a delayed complete response and a fresh retry result
    When the production complete completion is consumed
    Then the second attempt result is returned and exactly two bodies are captured

  Scenario: Warning mode continues the delayed original response
    Given a production U3 server with a delayed original response
    When the production complete completion is consumed
    Then the warning-mode original result is returned with exactly one body

  Scenario: Disabled mode preserves a delayed response
    Given a production U3 server with a delayed disabled response
    When the production complete completion is consumed
    Then the disabled result is returned with exactly one body

  Scenario: On-time complete response is not retried
    Given a production U3 server with an on-time complete response
    When the production complete completion is consumed
    Then the control result is returned with exactly one body

  Scenario: Raising mode retries delayed streaming headers
    Given a production U3 server with delayed streaming headers
    When the production streaming completion is consumed
    Then the second attempt result is returned and exactly two bodies are captured

  Scenario: Raising mode retries cumulative delayed streaming content
    Given a production U3 server with raising cumulative delayed streaming content
    When the production streaming completion is consumed
    Then the cumulative delayed stream retries with the fresh result

  Scenario: Raising mode preserves cumulative on-time streaming content
    Given a production U3 server with raising cumulative on-time streaming content
    When the production streaming completion is consumed
    Then the cumulative on-time stream completes without retry and without warnings

  Scenario: Warning mode continues cumulative delayed streaming content
    Given a production U3 server with cumulative delayed streaming content
    When the production streaming completion is consumed
    Then the delayed stream continues with one warning and one body

  Scenario: Disabled mode preserves delayed streaming content
    Given a production U3 server with disabled streaming monitoring
    When the production streaming completion is consumed
    Then the delayed stream is returned without warnings and one body
