Feature: Mock provider and executable conformance
  The Mock provider is both a readable conforming reference and a deterministic
  local fault injector. Conformance tests execute provider binaries without
  importing provider source or starting a Server, channel, or Cluster database.

  Scenario: Conformance accepts the Mock provider default mode
    Given the Mock provider runs in its default conforming mode
    When the executable conformance suite exercises every advertised function
    Then every response satisfies protocol framing and schema
    And every advertised capability has a successful representative case
    And no unadvertised capability is treated as supported

  Scenario: Conformance receives only an executable and local fixture configuration
    Given a provider executable is available
    When the conformance suite starts
    Then it does not import the provider source code
    And it does not start an Agent Cluster Server
    And it does not require an Endpoint database or network channel

  Scenario: Each fault has an independent local fixture
    Given the Mock provider has protocol fault fixtures
    When the fixture inventory is inspected
    Then malformed JSON, empty stdout, banner output, duplicate response, wrong request ID, timeout, oversized output, missing terminal, and duplicate terminal are separate modes
    And there is no single ambiguous broken mode standing in for all failures

  Scenario Outline: Protocol fault fixtures are detected by their matching assertion
    Given the Mock provider is started locally with fault fixture "<fixture>"
    When the executable conformance suite runs the matching case
    Then the case fails for "<expected>"
    And the failure is not reported as an unrelated business rejection

    Examples:
      | fixture            | expected                    |
      | malformed-json     | invalid JSON framing        |
      | empty-stdout       | missing response            |
      | stdout-banner      | extra stdout data           |
      | duplicate-response | multiple response documents |
      | wrong-request-id   | correlation mismatch        |
      | timeout            | invocation deadline         |
      | oversized-stdout   | stdout byte limit           |
      | missing-terminal   | interrupted stream          |
      | duplicate-terminal | duplicate terminal frame    |

  Scenario: A false capability advertisement is detected
    Given the Mock provider advertises query "model.catalog"
    But its local fixture returns unsupported for that query
    When conformance checks advertised behavior
    Then conformance fails for descriptor and behavior inconsistency

  Scenario: Generation race fixture proves same-path validation
    Given the Mock provider inspection reports "generation-1"
    And its local fixture changes the target to "generation-2" before execute
    When execute receives expected generation "generation-1"
    Then the provider rejects generation mismatch
    And conformance observes that no mutation was applied

  Scenario: Helper leak fixture is detected
    Given the Mock provider starts an invocation helper
    And its local fixture leaves the helper alive after the response
    When conformance completes the invocation
    Then conformance fails because the helper leaked
    And cleanup targets only the exact test-owned process

  Scenario: Custody fixture distinguishes an Agent from a helper
    Given the Mock provider starts a simulated durable Agent
    And completes a recorded independent custody handoff
    When the provider CLI exits
    Then the simulated Agent remains alive for the lifecycle assertion
    And later test cleanup terminates only that exact simulated Agent

  Scenario: Remote input cannot choose a Mock fixture
    Given the Mock provider starts in conforming mode
    When a protocol request contains "fault_mode"
    Then the request is rejected by schema validation
    And the provider remains in conforming mode

  Scenario: Provider projects do not import Cluster internal packages
    Given the Mock and TopsailAI providers are maintained as independent projects
    When provider project dependencies are inspected
    Then neither the Mock nor TopsailAI provider imports Agent Cluster internal packages
    And their integration dependency is only the published Adapter CLI protocol and schemas

  Scenario: Conformance validates provider-key repeatability
    Given the Mock provider has a stable resource fixture
    When discovery runs repeatedly across separate provider processes
    Then every run returns the same provider resource key
    And the same resource kind and generation semantics are preserved

  Scenario: Conformance validates reported concurrency constraints
    Given the Mock provider describes bounded total and operation-class limits
    When the conformance suite runs requests at those boundaries
    Then behavior does not contradict the described constraints
    And a provider limit is never interpreted as permission to exceed an Endpoint hard limit
