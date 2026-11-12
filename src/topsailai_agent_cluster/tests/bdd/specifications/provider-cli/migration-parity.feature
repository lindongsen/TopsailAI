Feature: Legacy adapter to provider CLI migration
  The existing TopsailAI Go adapter remains a temporary semantic oracle. Cutover
  compares Cluster-standard behavior rather than provider-native text or internal
  implementation details, and deletion happens only after rollback-safe acceptance.

  Background:
    Given the legacy TopsailAI adapter and the TopsailAI provider CLI are available
    And both use equivalent provider fixtures and local policy

  Scenario: Discovery parity compares standard observations
    When both paths discover the same provider resources
    Then they produce equivalent resource kinds and stable provider keys
    And they produce equivalent generations, states, state reasons, and observation completeness
    And Cluster IDs are mapped by the same Endpoint ResourceMapper

  Scenario: Unverified Session parity preserves safety
    Given the provider lists a Session without proving a live generation
    When both paths normalize the observation
    Then both report the Session as unverified or liveness unverified
    And both refuse live-process mutation that requires a generation
    And both allow only the standard exception explicitly defined for resume

  Scenario Outline: Standard query parity ignores provider-native formatting
    Given both paths support query "<query>"
    When both paths query the same fixture
    Then their Cluster-standard result documents are semantically equivalent
    And provider-native ordering or whitespace is not used as identity

    Examples:
      | query            |
      | launch.options   |
      | history.messages |
      | model.catalog    |
      | session.messages |

  Scenario: Mutation parity compares evidence boundaries
    Given both paths execute the same standard mutation against the same generation
    When their results are normalized
    Then delivery boundary is equivalent
    And provider outcome and effect certainty are equivalent
    And provider response and truncation evidence are preserved equivalently
    And neither path claims task completion from delivery alone

  Scenario: Provider rejection parity preserves the real provider error
    Given the provider rejects the same mutation through both paths
    When results are normalized
    Then both preserve the corresponding provider error code and bounded response
    And both report a proven non-application only when evidence supports it

  Scenario: Timeout parity preserves uncertainty
    Given provider execution crosses the side-effect boundary and then times out
    When both paths record the outcome
    Then both preserve unknown effect certainty
    And neither path automatically retries the mutation

  Scenario: Snapshot parity preserves truncation semantics
    Given the same output exceeds the requested snapshot budget
    When both paths read the snapshot
    Then both return valid UTF-8 within the budget
    And both label truncation and completeness equivalently

  Scenario: Follow parity preserves terminal semantics
    Given both paths follow the same output fixture
    When the provider stream ends normally
    Then both deliver equivalent records and one clean terminal outcome
    When the provider disappears without a terminal result
    Then both report interruption rather than clean completion

  Scenario: Drive parity preserves controller semantics
    Given a provider Session has a drive controller observation
    When both paths normalize the Session
    Then drive state and verification semantics are equivalent
    And stopping drive does not become stopping the Agent

  Scenario: Control action parity uses the approved action intersection
    Given the provider supports two control actions
    And Endpoint policy approves only one
    When both paths publish effective capabilities
    Then only the approved standard control action is visible
    And provider argv details are absent from the new effective capability

  Scenario: Cutover directs new work to the provider CLI
    Given parity, conformance, BDD, integration, and bounded live checks have passed
    And the legacy path remains available for rollback
    When the binding is atomically switched to the provider CLI
    Then new provider invocations use only the provider CLI path
    And existing durable command and resource identities remain valid

  Scenario: Failed cutover acceptance restores the legacy path
    Given the binding was switched to the provider CLI
    But post-cutover acceptance finds a blocking semantic difference
    When rollback is requested
    Then the previous binding path is restored
    And the Endpoint refreshes and publishes its restored effective capabilities
    And no provider mutation is replayed as part of rollback

  Scenario: Legacy implementation is deleted only after acceptance
    Given the provider CLI cutover has passed its retention and rollback window
    And no active binding references the legacy adapter
    When the removal logical unit begins
    Then the complete legacy dependency and call-site inventory is reviewed
    And the legacy adapter is removed without removing shared Endpoint abstractions
    And the full regression suite remains green
