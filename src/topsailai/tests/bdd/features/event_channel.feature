Feature: Push recorded events to external subscribers
  As an external tool
  I want to subscribe to a running session's event stream
  So that I receive events as they happen without polling

  Scenario: A subscriber receives events pushed over its link
    Given an event channel serving session "bdd-session"
    When a subscriber "sub-a" connects and subscribes to every event type
    And the session records a "tool_call.start" event
    Then subscriber "sub-a" receives that event over the link

  Scenario: A subscriber only receives the event types it asked for
    Given an event channel serving session "bdd-session"
    When a subscriber "sub-b" connects and subscribes to "tool_call.*"
    And the session records a "llm.response.raw" event
    And the session records a "tool_call.end" event
    Then subscriber "sub-b" receives only the "tool_call.end" event

  Scenario: A heartbeat keeps the link alive and is acknowledged
    Given an event channel serving session "bdd-session"
    When a subscriber "sub-c" connects and subscribes to every event type
    And the subscriber sends heartbeat sequence 7
    Then the server acknowledges heartbeat sequence 7
    And subscriber "sub-c" is still registered

  Scenario: A dropped link stops delivery and frees the subscriber
    Given an event channel serving session "bdd-session"
    When a subscriber "sub-d" connects and subscribes to every event type
    And the subscriber closes the link
    Then subscriber "sub-d" is no longer registered
    And a later recorded event is delivered to nobody

  Scenario: A reconnect with the same identity replaces the old link
    Given an event channel serving session "bdd-session"
    When a subscriber "sub-e" connects and subscribes to every event type
    And the same subscriber "sub-e" reconnects
    Then only one link exists for subscriber "sub-e"
    And an event recorded after the reconnect arrives exactly once

  Scenario: Unsubscribing closes the link
    Given an event channel serving session "bdd-session"
    When a subscriber "sub-f" connects and subscribes to every event type
    And the subscriber unsubscribes
    Then the server confirms the unsubscribe
    And subscriber "sub-f" is no longer registered

  Scenario: A silent subscriber is reclaimed after the heartbeat timeout
    Given an event channel serving session "bdd-session" with a 0.2 second heartbeat timeout
    When a subscriber "sub-g" connects and subscribes to every event type
    And the subscriber stops sending heartbeats
    Then subscriber "sub-g" is reclaimed without an explicit disconnect

  Scenario: A slow subscriber cannot delay the producer
    Given an event channel serving session "bdd-session" with a 2 event queue
    When a subscriber "sub-h" connects and subscribes to every event type
    And the subscriber stops reading while 5 events are recorded
    Then recording all 5 events completes without blocking
    And the subscriber queue stays bounded instead of growing without limit

  Scenario: An operator can see how many events were dropped
    Given an event channel serving session "bdd-session" with a 2 event queue
    And a subscriber "sub-i" that never drains its queue
    When the session records 5 events
    Then the runtime view reports 3 dropped events

  Scenario: A healthy channel publishes no drop state
    Given an event channel serving session "bdd-session" with a 100 event queue
    And a subscriber "sub-j" that never drains its queue
    When the session records 3 events
    Then the runtime view reports no dropped events

  Scenario: A real approval decision reaches a subscriber
    Given an event channel serving session "bdd-session" with a 30 second heartbeat timeout
    And a subscriber "sub-k" connects and subscribes to "tool_approval.*"
    And an approval rule that requires a human decision for tool "danger_tool"
    When the tool "danger_tool" is approved by the human
    Then subscriber "sub-k" receives the approval request event
    And subscriber "sub-k" receives the approval decision event
    And the approval decision event reports status "approved"
