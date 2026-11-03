Feature: non-interactive TUI
  Scenario: non-interactive list returns every endpoint and session
    Given a real cluster with a healthy provider for the TUI
    When the TUI list command is run without a TTY
    Then the TUI list JSON contains the endpoint, adapter, session, generation, and state

  Scenario: non-interactive show returns complete session details
    Given a real cluster with a healthy provider for the TUI
    When the TUI show command is run for the fixture session
    Then the TUI show JSON contains the session and capability list

  Scenario: unsupported TUI action is rejected without provider invocation
    Given a real cluster with a healthy provider for the TUI
    When the TUI unsupported action is run with confirmation
    Then the TUI action is rejected as unsupported
    And the TUI provider invocation count is zero

  Scenario: TUI stop without generation is rejected
    Given a real cluster with a healthy provider for the TUI
    When the TUI stop command is run without a generation
    Then the TUI stop action is rejected because generation is required
    And the TUI provider invocation count is zero

  Scenario: TUI status wording preserves lifecycle evidence
    Given a real cluster with a healthy provider for the TUI
    When the TUI status wording is evaluated
    Then submitted is not displayed as ready
    And the output contains "request delivered"

  Scenario: non-interactive TUI works without a TTY
    Given a real cluster with a healthy provider for the TUI
    When the TUI list JSON is run in a no-TTY subprocess
    Then the no-TTY TUI output is valid structured JSON


  Scenario Outline: tui renders each command state with distinct wording
    Given a running cluster with one endpoint
    And a command in state "<state>"
    When I run the tui show command in human readable mode
    Then the output contains "<wording>"

    Examples:
      | state            | wording          |
      | admitted         | server received  |
      | dispatched       | request delivered |
      | endpoint_admitted | endpoint received |
      | effect_unknown   | effect unknown   |
      | finished         | confirmed result |
      | rejected         | failed           |
      | failed           | failed           |

  Scenario: tui show lists recent commands for a session
    Given a running cluster with one endpoint
    And a session with at least one submitted command
    When I run the tui show command in human readable mode
    Then the output contains the command id prefix
    And the output contains the command status

  Scenario: tui list shows endpoint without sessions
    Given a running cluster with one endpoint reporting no sessions
    When I run the tui list command in human readable mode
    Then the output contains the endpoint hostname
    And the output contains "no sessions"
    And the output contains "LAST_SUCCESS"


  Scenario: tui logs returns bounded snapshot
    Given a running cluster with one endpoint
    And a session with provider output
    When I run the tui logs command with max bytes 16
    Then the output length is at most 16 and truncated

  Scenario: tui logs reports unsupported capability
    Given a running cluster with one endpoint
    And a session whose adapter does not support output reading
    When I run the tui logs command
    Then the output contains "unsupported"

  Scenario: tui logs returns snapshot larger than websocket default read limit
    Given a running cluster with one endpoint
    And a session with provider output larger than 32768 bytes
    When I run the tui logs command with max bytes 65536
    Then the output length is greater than 32768
