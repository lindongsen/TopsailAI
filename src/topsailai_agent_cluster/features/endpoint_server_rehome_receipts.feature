Feature: Endpoint re-home receipt settlement

  An Endpoint keeps every recorded receipt in its journal and re-sends them after
  a reconnect, because a receipt that was never acknowledged may still be needed.
  A re-home changes which Server receives those receipts, and a Server that never
  admitted a command can never apply its receipt. These scenarios prove the
  Endpoint settles exactly the receipts that can never be applied, and keeps the
  one that proves a real disagreement.

  A receipt ends its resend obligation in one of two ways, and the two are
  different events. An acknowledgement means the Server stored the receipt, so it
  is settled immediately and never re-sent. A rejection means the Server refused
  it, and only a rejection that can never become applicable settles it. The
  rejection scenarios therefore have to lose the acknowledgement first: while the
  acknowledgement arrives, the receipt is settled before any Server can refuse it,
  so a rejection is only reachable for a receipt the Endpoint still holds because
  it never learned the Server stored it.

  Scenario: a receipt the new server never admitted is settled
    Given a real cluster with a second server for receipt settlement whose acknowledgement is lost
    And a command has been executed and its receipt recorded
    When the endpoint re-homes to a second server that never admitted the command
    Then the endpoint settles the receipt as unknown command
    And the endpoint no longer re-sends the settled receipt

  Scenario: an acknowledged receipt is settled and never re-sent
    Given a real cluster with a receipt settlement journal whose acknowledgement is delivered
    And a command has been executed and its receipt recorded
    Then the endpoint settles the receipt as acknowledged
    And the endpoint no longer re-sends the settled receipt

  Scenario: a reconnect to the same server settles nothing
    Given a real cluster with a receipt settlement journal whose acknowledgement is lost
    And a command has been executed and its receipt recorded
    When the server restarts and the endpoint reconnects to the same server
    Then the endpoint settles no receipt

  Scenario: a receipt older than the stored revision is settled
    Given a real cluster with a receipt settlement journal whose acknowledgement is lost
    And a command has been executed and its receipt recorded
    When the server stores a newer revision of that receipt
    Then the endpoint settles the receipt as revision stale

  Scenario: a receipt that conflicts at the same revision is never settled
    Given a real cluster with a receipt settlement journal whose acknowledgement is lost
    And a command has been executed and its receipt recorded
    When the server stores a different receipt at the same revision
    Then the endpoint settles no receipt
    And the endpoint reports the rejection as kept pending
