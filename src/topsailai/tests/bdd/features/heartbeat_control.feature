Feature: Probe control-channel liveness
  As an operator
  I want a correlated heartbeat from the control channel
  So that I can check endpoint responsiveness without changing conversation state

  Scenario Outline: A live endpoint reports its own identity and session
    Given a heartbeat control server with session "<session>"
    When the operator probes heartbeat through JSONL and the CLI transport
    Then the heartbeat echoes the request and reports the serving identity
    Examples:
      | session     |
      | bdd-session |
      | missing     |
      | empty       |

  Scenario: Repeated heartbeat probes leave conversation state unchanged
    Given a heartbeat control server with session "bdd-session"
    When the operator sends three heartbeat probes
    Then every heartbeat succeeds without changing conversation state

  Scenario: A stopped endpoint cannot answer a heartbeat
    Given a heartbeat control server with session "bdd-session"
    When the operator stops the responsive heartbeat server
    Then a new heartbeat connection fails at the transport boundary

  Scenario: Heartbeat rejects a nonempty payload
    Given a heartbeat control server with session "bdd-session"
    When the operator sends a heartbeat with a nonempty payload
    Then the heartbeat response rejects the payload without reporting false liveness

  Scenario: Unknown actions remain rejected
    Given a heartbeat control server with session "bdd-session"
    When the operator sends an unknown heartbeat action
    Then the control server reports the unknown action
