Feature: Provider mutation execution and generation safety
  The Endpoint owns admission, journal state, and complete Cluster receipts.
  The provider receives only the minimum provider target and must revalidate the
  expected generation in the same path that performs a mutation.

  Background:
    Given an admitted mutating Cluster command
    And the Endpoint has resolved its Cluster target to a configured Adapter instance and key

  Scenario: A provider mutation receives a minimal request
    When the Endpoint prepares the provider execute request
    Then the request contains a stable opaque "invocation_id"
    And the request contains the standard operation name and version
    And the request contains "provider_resource_key" and "expected_generation"
    And the request contains the typed operation payload and bounded deadline
    And the request does not contain operator credentials
    And the request does not grant Cluster resource ID authority
    And the request does not contain the Endpoint journal phase or command revision

  Scenario: Preflight inspection rejects a known generation mismatch
    Given the requested generation is "generation-1"
    And provider inspection observes "generation-2"
    When the Endpoint performs preflight inspection
    Then the command is rejected for generation mismatch
    And provider execute is not invoked

  Scenario: Execute revalidates generation after a successful preflight
    Given preflight inspection observes "generation-1"
    And the target changes to "generation-2" before mutation
    When provider execute receives expected generation "generation-1"
    Then the provider rejects the mutation for generation mismatch
    And no mutation is applied to generation "generation-2"

  Scenario: A provider without same-path generation validation cannot advertise mutation
    Given the provider can inspect a target but cannot revalidate during mutation
    When its effective mutation capabilities are computed
    Then the affected mutation is not published as safely supported
    And an attempted request returns unsupported or generation validation unavailable

  Scenario: The Endpoint constructs the complete ExecutionReceipt
    Given the provider returns bounded execution evidence
    When the Endpoint records the result
    Then the Endpoint constructs the complete "ExecutionReceipt"
    And the Endpoint supplies the Cluster command ID and request hash
    And the Endpoint supplies its instance identity, journal phase, and command revision
    And the provider evidence supplies delivery boundary, provider outcome, and provider response
    And the provider cannot choose the final journal phase

  Scenario: A provider response claiming a complete Cluster receipt is rejected
    Given the provider response includes an Endpoint journal phase and Cluster command revision
    When the response is validated
    Then the response is rejected as a protocol violation
    And the claimed journal values are not persisted

  Scenario: Endpoint may downgrade uncertain provider evidence
    Given the provider claims acknowledged delivery
    But the process exits before a complete correlated response is validated
    When the Endpoint determines effect certainty
    Then the effect remains unknown
    And the Endpoint does not upgrade the incomplete evidence to success
    And the command is not replayed automatically

  Scenario: Provider business rejection proves no application
    Given the provider returns a valid rejection before attempting the mutation
    And the result proves the operation was not applied
    When the Endpoint records the result
    Then effect certainty is not_applied
    And the provider error code and bounded response are preserved

  Scenario: A repeated Cluster command reuses its provider invocation ID
    Given a command crossed an uncertain provider boundary
    When recovery queries or resubmits the same admitted command where the protocol allows it
    Then the same opaque invocation ID is used
    And a new invocation ID is not created silently

  Scenario: Changed intent cannot reuse an invocation ID
    Given invocation ID "invocation-1" is bound to one canonical operation and target
    When a request reuses "invocation-1" with a changed payload or target
    Then the request is rejected as an identity conflict
    And the changed mutation is not executed

  Scenario: Query command uses provider correlation without transferring journal authority
    Given the provider returned provider request reference "provider-ref-1"
    When the Endpoint invokes query_command during recovery
    Then the provider receives the stable invocation ID and provider reference
    And the provider returns only provider reconciliation evidence
    And the Endpoint alone changes the Cluster command state

  Scenario: Provider execution timeout preserves unknown effects
    Given the provider process exceeds its mutation deadline after invocation begins
    When the Generic CLI Adapter cancels the invocation
    Then the exact owned invocation process group is cleaned up
    And the command records unknown effect unless non-application is proven
    And no broad process-name termination is used

  Scenario: Public command exec does not invoke a provider CLI
    Given an operator submits the standard "command.exec" operation
    When the Endpoint executes the allowlisted command
    Then the Endpoint itself enforces argv, working-directory, environment, timeout, and output policy
    And the Generic CLI Adapter is not used to execute the allowlisted command

  Scenario: Internal provider process invocation is not public command exec
    Given the Generic CLI Adapter needs to start a configured provider executable
    When the Endpoint invokes that executable
    Then it uses the fixed Endpoint-local executable configuration directly
    And no public "command.exec" intent is created recursively
    And no session command allowlist selects the provider executable
