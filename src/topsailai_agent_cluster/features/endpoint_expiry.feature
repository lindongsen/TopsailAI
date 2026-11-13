Feature: offline endpoint expiry lifecycle

  # The lifecycle has four states: live, offline, inventory expired, metadata
  # expired. Every scenario below asserts one transition or one safety boundary,
  # through the real Server HTTP boundary rather than through storage directly.

  Scenario: a legacy offline row is repaired and expired
    Given a real cluster whose server database holds a legacy offline endpoint "legacy-1" and an endpoint retention of "1s"
    When the server completes at least one expiry sweep
    Then endpoint "legacy-1" is absent from the endpoint list
    And the inventory for "legacy-1" is not found

  Scenario: a connected endpoint is never expired
    Given a real cluster with an endpoint retention of "1s"
    When the server completes at least one expiry sweep
    Then endpoint "endpoint-1" is present in the endpoint list

  Scenario: a recent offline row is retained
    Given a real cluster whose server database holds a recent offline endpoint "recent-1" and an endpoint retention of "1h"
    When the server completes at least one expiry sweep
    Then endpoint "recent-1" is present in the endpoint list
    And the inventory for "recent-1" is present

  Scenario: retained command evidence blocks metadata deletion
    Given a real cluster whose server database holds a legacy offline endpoint "referenced-1" with a terminal command and endpoint retention "1s" and command retention "1h"
    When the server completes at least one expiry sweep
    Then the inventory for "referenced-1" is not found
    And endpoint "referenced-1" is present in the endpoint list
    And command "cmd-referenced-1" is still readable through the command API

  Scenario: command retention unblocks metadata deletion
    Given a real cluster whose server database holds a legacy offline endpoint "purged-1" with a terminal command and endpoint retention "1s" and command retention "1s"
    When the server completes at least one expiry sweep
    Then the inventory for "purged-1" is not found
    And endpoint "purged-1" is absent from the endpoint list
    And command "cmd-purged-1" is no longer readable through the command API

  Scenario: an uncertain command is never purged
    Given a real cluster whose server database holds a legacy offline endpoint "uncertain-1" with an unconfirmed command and endpoint retention "1s" and command retention "1s"
    When the server completes at least one expiry sweep
    Then the inventory for "uncertain-1" is not found
    And command "cmd-uncertain-1" is still readable through the command API
    And endpoint "uncertain-1" is present in the endpoint list
