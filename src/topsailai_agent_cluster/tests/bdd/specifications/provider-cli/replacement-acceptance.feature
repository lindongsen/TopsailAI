Feature: Provider CLI replacement acceptance
  The independent Provider CLI must satisfy the Cluster contract without retaining the old
  CommandAdapter or compiled-in provider implementation as a legacy, fallback, parity or rollback path.

  Background:
    Given the Cluster Provider CLI contract is frozen
    And the executable conformance suite passes against the mock provider
    And the TopsailAI Provider CLI is installed at an immutable versioned path


  Scenario: an unverified Session preserves fail-closed admission
    Given the provider lists a Session without proving a live generation
    When the Provider CLI returns the standard observation
    Then Endpoint reports the Session as unverified or liveness unverified
    And Endpoint refuses live-process mutation that requires a generation
    And Endpoint allows only the standard exception explicitly defined for resume

  Scenario Outline: every standard query satisfies its Cluster schema
    Given the Provider CLI advertises query "<query>"
    When Endpoint invokes that query against the provider-neutral fixture
    Then the result satisfies the registered Cluster schema for "<query>"
    And provider-native ordering or whitespace is not used as identity

    Examples:
      | query            |
      | launch.options   |
      | history.messages |
      | model.catalog    |
      | session.messages |

  Scenario: mutation preserves evidence boundaries
    Given the Provider CLI executes a standard mutation against the expected generation
    When Endpoint composes the command receipt
    Then delivery boundary comes only from validated provider evidence
    And provider outcome and effect certainty remain distinct
    And provider response and truncation evidence are preserved
    And Endpoint does not claim task completion from delivery alone

  Scenario: provider rejection preserves the real provider error
    Given the provider rejects a standard mutation before applying it
    When the Provider CLI returns its bounded standard error evidence
    Then Endpoint preserves the corresponding provider error code and response
    And Endpoint reports proven non-application only when evidence supports it

  Scenario: timeout after possible delivery preserves uncertainty
    Given provider execution crosses the side-effect boundary and then times out
    When Endpoint records the outcome
    Then effect certainty is unknown
    And Endpoint does not automatically retry the mutation

  Scenario: snapshot preserves UTF-8 truncation semantics
    Given provider output exceeds the requested snapshot budget
    When the Provider CLI returns the bounded snapshot
    Then the result is valid UTF-8 within the budget
    And truncation and completeness are labelled explicitly

  Scenario: follow reports one clean terminal outcome
    Given the Provider CLI follows a provider-neutral output fixture
    When the provider stream ends normally
    Then the stream delivers the expected records and one clean terminal outcome

  Scenario: follow interruption is not clean completion
    Given the Provider CLI follows a provider-neutral output fixture
    When the provider disappears without a terminal result
    Then Endpoint reports interruption rather than clean completion

  Scenario: drive preserves controller semantics
    Given a provider Session has a drive-controller observation
    When the Provider CLI returns the standard Session observation
    Then drive state and verification satisfy the Cluster contract
    And stopping drive does not become stopping the Agent

  Scenario: control actions use the approved intersection
    Given the Provider CLI describes two standard control actions
    And Endpoint policy approves only one
    When Endpoint computes effective capabilities
    Then only the approved standard control action is visible
    And provider argv details are absent from the effective capability

  Scenario: the replacement is accepted from contract evidence
    Given provider-neutral fixtures define the expected standard observations and execution evidence
    When the TopsailAI Provider CLI runs the fixtures through the Generic CLI Adapter
    Then every result satisfies the frozen Cluster schemas and semantic assertions
    And acceptance does not invoke the old CommandAdapter
    And acceptance does not invoke the compiled-in TopsailAI adapter

  Scenario: bounded live smoke proves effects that fixtures cannot prove
    Given fixture tests cannot prove the lifecycle of a real provider business resource
    When the bounded live smoke starts and observes that resource through the Provider CLI
    Then the observed lifecycle satisfies the Cluster operation contract
    And the provider invocation helper exits without terminating the handed-off resource
    And cleanup targets only resources created by the smoke scenario

  Scenario: production Endpoint contains one provider seam
    When the Provider CLI replacement is built for production
    Then Endpoint routes configured Adapter instances only through the Generic CLI Adapter
    And the old CommandAdapter and its argv protocol are absent
    And the compiled-in TopsailAI factory path is absent
    And provider command templates and placeholder substitution are absent

  Scenario: Endpoint starts with no configured Adapter
    Given no Provider package is active
    And Endpoint has zero configured Adapter instances
    When Endpoint starts
    Then Endpoint connects to Server
    And Endpoint reports its own health
    And Endpoint reports zero Adapter instances
    And Endpoint waits for local Adapter configuration

  Scenario: one Adapter is activated without restarting Endpoint
    Given Endpoint is online with zero or more unrelated Adapter instances
    And a verified TopsailAI Provider CLI version is installed
    When agent-clusterctl requests a per-adapter replace for adapter ID "topsailai-work"
    Then Endpoint validates the immutable executable and protocol
    And Endpoint atomically installs the new Adapter instance
    And Endpoint publishes the new effective capability revision before accepting mutation
    And Endpoint does not restart
    And unrelated Adapter instances remain available

  Scenario: replacement activation fails closed
    Given the candidate Provider CLI fails describe, conformance, or bounded smoke validation
    When agent-clusterctl requests activation
    Then the target Adapter instance is not changed
    And no new capability revision is published
    And mutating operations are not routed to the rejected candidate
    And Endpoint remains online

  Scenario: rollback selects a previous Provider CLI version
    Given adapter ID "topsailai-work" uses a verified Provider CLI version
    And another previously verified immutable Provider CLI version is retained
    When agent-clusterctl requests rollback for that Adapter
    Then Endpoint replaces only that Adapter with the previous Provider CLI version
    And Endpoint publishes the effective capability revision for the restored version
    And Endpoint does not restore the old CommandAdapter
    And Endpoint does not restore the compiled-in TopsailAI adapter

  Scenario: removal is part of the reviewed replacement unit
    When the Provider CLI replacement logical unit is reviewed
    Then its diff includes deletion of the old CommandAdapter production path
    And its diff includes deletion of the compiled-in TopsailAI factory production path
    And its diff includes deletion of provider command templates
    And no follow-up legacy-removal unit is required
