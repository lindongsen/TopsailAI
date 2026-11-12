Feature: Provider output snapshots and streams
  Output snapshots are bounded documents and output follow uses correlated JSON Lines framing.
  A missing terminal frame or a broken provider process must never be presented as a clean end of output.

  Background:
    Given an Endpoint with a provider that supports output reads
    And output access has already passed Endpoint authorization

  Scenario: A bounded snapshot preserves completeness evidence
    Given the provider has more output than the requested byte budget
    When the Endpoint requests an output snapshot
    Then the provider returns content within the budget
    And truncation or partial evidence is explicit
    And the shortened content is not presented as complete history

  Scenario: Snapshot truncation preserves valid UTF-8
    Given provider output contains a multibyte UTF-8 character at the byte boundary
    When the provider truncates the snapshot to the requested budget
    Then the returned content ends on a valid UTF-8 boundary
    And the snapshot is labelled truncated

  Scenario: A normal follow stream has one start and one terminal frame
    When the Endpoint starts output follow with request ID "follow-1"
    Then stdout contains one correlated start frame
    And stdout contains zero or more correlated record frames
    And stdout ends with exactly one correlated terminal frame
    And every frame uses request ID "follow-1"

  Scenario: Follow records remain individually bounded
    Given one provider output record exceeds the per-record byte budget
    When the record is emitted through output follow
    Then the record is truncated on a valid UTF-8 boundary
    And that record is labelled truncated
    And later records may still be delivered

  Scenario: EOF without a terminal frame is interrupted
    Given the provider emits a start frame and output records
    But the provider exits before a terminal frame
    When the Generic CLI Adapter reads EOF
    Then the follow ends as stream_interrupted
    And the delivered records are not presented as a clean complete stream

  Scenario: A duplicate terminal frame is a protocol failure
    Given the provider emits two terminal frames for one follow request
    When the stream is validated
    Then the stream fails with a protocol error
    And the second terminal frame is not accepted as another completion

  Scenario: A record after the terminal frame is rejected
    Given the provider emits a terminal frame
    And then emits another output record
    When the stream is validated
    Then the stream fails with a protocol error
    And the late record is not delivered as valid output

  Scenario: A mismatched stream request ID cannot cross-complete another follow
    Given follow request "follow-1" is active
    And the provider emits a frame for "follow-2"
    When the frame is validated
    Then the frame is rejected for correlation mismatch
    And follow request "follow-1" remains incomplete until its own terminal outcome

  Scenario: Operator cancellation stops only the follow invocation
    Given output follow is active for a running Agent
    When the operator cancels the follow
    Then the provider follow invocation receives cancellation
    And its invocation helper process is cleaned up
    And the Agent remains running
    And the stream reports cancellation when the terminal channel remains writable

  Scenario: Provider stream error preserves its error code
    Given the provider emits a valid terminal error frame
    When the Endpoint completes the follow
    Then the provider error code and bounded diagnostic are preserved
    And the outcome is not rewritten as clean completion

  Scenario: Provider process loss is not a provider-reported terminal error
    Given the provider process terminates without a valid terminal frame
    When the Endpoint completes the follow
    Then the outcome is stream_interrupted or a process failure
    And no provider terminal code is fabricated

  Scenario: Output follow capacity is independent by binding
    Given binding "binding-a" has exhausted its follow capacity
    And binding "binding-b" has available follow capacity
    When a follow is requested from binding "binding-b"
    Then binding "binding-b" admits the follow
    And binding "binding-a" remains at its configured limit

  Scenario: A slow output consumer cannot starve mutation capacity
    Given a follow consumer is slower than the provider output rate
    When the Endpoint output queue reaches its bound
    Then the output path pauses, expires, or reports an explicit gap according to capability
    And mutation and heartbeat capacity remains available
    And no unbounded queue is created
