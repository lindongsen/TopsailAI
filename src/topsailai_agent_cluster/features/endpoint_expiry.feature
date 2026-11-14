Feature: offline endpoint degradation and expiry lifecycle

  # The lifecycle has five states: online, offline, degraded, inventory removed,
  # metadata removed. Degrading and expiring are separate transitions because
  # they answer different questions: degrading decides that a disconnected
  # machine is no longer usable, expiring decides that the record of that machine
  # stops existing. Every scenario below asserts one transition or one safety
  # boundary, through the real Server HTTP boundary rather than through storage
  # directly.

  Scenario: a legacy offline row is degraded instead of deleted
    Given a real cluster whose server database holds a legacy offline endpoint "legacy-1" and an endpoint retention of "1s"
    When the server completes at least one expiry sweep
    Then endpoint "legacy-1" is present in the endpoint list
    And endpoint "legacy-1" is degraded in the endpoint list
    And endpoint "legacy-1" is listed with a deletion date
    And the inventory for "legacy-1" is not found

  Scenario: a connected endpoint is never degraded
    Given a real cluster with an endpoint retention of "1s"
    When the server completes at least one expiry sweep
    Then endpoint "endpoint-1" is present in the endpoint list
    And endpoint "endpoint-1" is online in the endpoint list
    And endpoint "endpoint-1" is not listed with a deletion date

  Scenario: a recent offline row is retained
    Given a real cluster whose server database holds a recent offline endpoint "recent-1" and an endpoint retention of "1h"
    When the server completes at least one expiry sweep
    Then endpoint "recent-1" is present in the endpoint list
    And endpoint "recent-1" is offline in the endpoint list
    And endpoint "recent-1" is not listed with a deletion date
    And the inventory for "recent-1" is present

  Scenario: a degraded endpoint is retained before its deletion deadline
    Given a real cluster whose server database holds a degraded endpoint "waiting-1" with a future deletion deadline and an endpoint retention of "1s"
    When the server completes at least one expiry sweep
    Then endpoint "waiting-1" is present in the endpoint list
    And endpoint "waiting-1" is degraded in the endpoint list
    And endpoint "waiting-1" is listed with a deletion date

  Scenario: a degraded endpoint is deleted once its deletion deadline passes
    Given a real cluster whose server database holds a degraded endpoint "expired-1" with a past deletion deadline and an endpoint retention of "1s"
    When the server completes at least one expiry sweep
    Then endpoint "expired-1" is absent from the endpoint list
    And the inventory for "expired-1" is not found

  Scenario: retained command evidence survives degradation
    Given a real cluster whose server database holds a legacy offline endpoint "referenced-1" with a terminal command and endpoint retention "1s" and command retention "1h"
    When the server completes at least one expiry sweep
    Then endpoint "referenced-1" is degraded in the endpoint list
    And the inventory for "referenced-1" is not found
    And command "cmd-referenced-1" is still readable through the command API

  Scenario: an uncertain command is never purged by age
    Given a real cluster whose server database holds a legacy offline endpoint "uncertain-1" with an unconfirmed command and endpoint retention "1s" and command retention "1s"
    When the server completes at least one expiry sweep
    Then endpoint "uncertain-1" is degraded in the endpoint list
    And the inventory for "uncertain-1" is not found
    And command "cmd-uncertain-1" is still readable through the command API

  Scenario: deleting a degraded endpoint removes its command evidence
    Given a real cluster whose server database holds a degraded endpoint "cascaded-1" with an unconfirmed command and a past deletion deadline and an endpoint retention of "1s"
    When the server completes at least one expiry sweep
    Then endpoint "cascaded-1" is absent from the endpoint list
    And command "cmd-cascaded-1" is no longer readable through the command API
