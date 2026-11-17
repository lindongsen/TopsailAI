Feature: Endpoint fallback and the absence of automatic switch-back

  An Endpoint configured with an ordered address list walks that list from the
  first entry on every reconnect, so a Server that stops answering is walked past
  without operator action. That makes fallback automatic in both directions: when
  the first Server fails the Endpoint moves to the second, and when the second
  fails it moves back to the first.

  Switch-back does not happen while the current link is healthy, because a
  reconnect only starts after that link fails. A restored first Server therefore
  does not pull the Endpoint back on its own.

  A Server that stops answering is not the same failure as a Server that goes
  away. A closed socket produces an immediate read error, so a build with no
  liveness detection still reconnects and the scenario would pass for the wrong
  reason. Only a Server that keeps its sockets open and stops replying proves
  that the Endpoint decided the Server was unhealthy.

  Background:
    Given a real cluster in the endpoint-initiated channel direction with a second server behind a proxy

  Scenario: an Endpoint falls back to the second Server when the first Server stops
    Given the endpoint holds a generation higher than the second server will assign
    When the primary server stops
    Then the second server reports the endpoint online
    And the second server accepts an inventory report from the endpoint
    And the endpoint reports the refused primary address as a failed attempt
    And the endpoint does not report a superseded connection

  Scenario: an Endpoint returns to the first Server when the second Server stops answering
    Given the endpoint holds a generation higher than the second server will assign
    And the primary server stops and the endpoint re-homes to the second server
    And the primary server is restored and answers health checks
    When the second server stops answering without closing its connections
    Then the endpoint reports the second server as unhealthy
    And the primary server reports the endpoint online

  Scenario: a restored first Server does not pull the Endpoint back on its own
    Given the endpoint holds a generation higher than the second server will assign
    And the primary server stops and the endpoint re-homes to the second server
    When the primary server is restored and answers health checks
    Then the endpoint does not attempt a reconnect within the observation window
    And the second server still reports the endpoint online
