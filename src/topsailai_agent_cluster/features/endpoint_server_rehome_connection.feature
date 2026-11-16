Feature: Endpoint re-home connection layer

  An Endpoint belongs to exactly one Server at a time. Moving it to another Server is a re-home,
  not a failover: the new Server has its own database and its own fence, so it assigns a generation
  that can be lower than the one the Endpoint already holds. These scenarios prove the Endpoint
  adopts that lower generation instead of rejecting the link forever.

  Background:
    Given a real cluster in the endpoint-initiated channel direction with a second server

  Scenario: an Endpoint adopts a Server whose generation is lower than the one it holds
    Given the endpoint holds a generation higher than the second server will assign
    When the endpoint re-homes to the second server
    Then the second server reports the endpoint online
    And the second server accepts an inventory report from the endpoint
    And the endpoint does not report a superseded connection

  Scenario: an Endpoint reconnects to a restarted Server
    Given the endpoint holds a generation higher than the second server will assign
    When the server restarts and assigns a lower generation again
    Then the endpoint reconnects to the restarted server
    And the endpoint does not report a superseded connection
