Feature: Endpoint re-home deployment shapes

  An Endpoint belongs to exactly one Server at a time, and which side dials is a
  deployment decision rather than a protocol one. An Endpoint may be configured
  with an ordered list of Servers, or with no Server at all when the Server dials
  it. These scenarios prove both shapes work, that the ordered list is walked past
  a failure instead of stopping at it, that a provider fault is still visible
  after a re-home, and that a command in flight when the Endpoint moves is
  reported as unknown rather than silently re-sent.

  Scenario: an Endpoint with no configured Server waits for the Server to dial
    Given a real cluster where the server dials the endpoint
    Then the endpoint reports online without a configured server address
    And the server accepts an inventory report from the endpoint
    And the endpoint reports that no server address is configured

  Scenario: an Endpoint walks past an unreachable address to a working Server
    Given a real cluster whose first configured address is unreachable
    Then the endpoint reports online through the second address
    And the endpoint reports the unreachable address as a failed attempt

  Scenario: a provider fault is still visible after a re-home
    Given a real cluster with a second server and a failing provider
    When the endpoint re-homes to the second server and reports online
    Then a command submitted after the re-home fails with the provider error
    And the failure names the provider rather than the connection

  Scenario: a command in flight during a re-home is reported as unknown
    Given a real cluster with a second server and a slow provider
    And a command is submitted with a deadline shorter than the provider hold
    When the endpoint re-homes while the command is still executing
    Then the command converges to unconfirmed with unknown effect
    And the provider was invoked exactly once
