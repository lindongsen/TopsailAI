Feature: CLI Server failover across an ordered profile group

  The CLI accepts an ordered group of Server profiles, such as
  `primary,secondary`. Position is preference: the CLI probes candidates in that
  order and uses the first one that can serve the request.

  Only unreachability causes a switch. A Server that refuses the credential, or
  that answers with any other non-success status, stops the walk, because both
  mean the Server is healthy and the answer is real. Falling back past either one
  would hide the real cause behind a successful-looking second attempt.

  The CLI remembers the last Server that answered and tries it first. This is not
  a convenience. An Endpoint only reconnects on transport failure, so after a
  primary recovers the fleet stays on the secondary. A CLI that always probed from
  the head of the group would return to the primary and report an empty fleet,
  which reads as a total outage.

  A group of one is used without probing, so an existing single-Server deployment
  keeps its exact behaviour and gains no new failure mode.

  Background:
    Given a real cluster with a second independent server

  Scenario: the CLI uses the first Server when it is reachable
    When the CLI runs a read command with the profile group "primary,secondary"
    Then the CLI exits successfully
    And the CLI reports it used server profile "primary"
    And the CLI reports no skipped server

  Scenario: the CLI falls back to the second Server when the first is unreachable
    Given the primary server is stopped
    When the CLI runs a read command with the profile group "primary,secondary"
    Then the CLI exits successfully
    And the CLI reports it used server profile "secondary"
    And the CLI reports server profile "primary" as skipped

  Scenario: a restored first Server does not pull the CLI back while the second is remembered
    Given the CLI remembers server profile "secondary"
    When the CLI runs a read command with the profile group "primary,secondary"
    Then the CLI exits successfully
    And the CLI reports it used server profile "secondary"
    And the CLI reports no skipped server

  Scenario: a single profile is used without probing
    When the CLI runs a read command with the profile group "primary"
    Then the CLI exits successfully
    And the CLI reports no server selection
    And the CLI writes no remembered server profile

  Scenario: the CLI names every Server when none is reachable
    Given the primary server is stopped
    And the second server is stopped
    When the CLI runs a read command with the profile group "primary,secondary"
    Then the CLI fails
    And the CLI error names server profile "primary"
    And the CLI error names server profile "secondary"
