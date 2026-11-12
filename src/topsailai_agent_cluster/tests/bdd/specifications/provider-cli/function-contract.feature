Feature: Standard Adapter CLI function contract
  The Cluster defines a closed set of Adapter CLI functions. A provider advertises
  only the functions it implements and returns explicit unsupported outcomes for
  optional functions instead of substituting unrelated behavior.

  Scenario Outline: An advertised function accepts its Cluster-defined request shape
    Given the provider descriptor advertises function "<function>"
    And the request satisfies the Cluster schema for "<function>"
    When the Endpoint invokes "<function>"
    Then the provider returns the Cluster-defined result shape for "<function>"
    And request correlation and protocol version are preserved

    Examples:
      | function       |
      | describe       |
      | discover       |
      | inspect        |
      | execute        |
      | query          |
      | query_command  |
      | read_output    |
      | follow_output  |
      | watch          |

  Scenario Outline: An optional unadvertised function is explicitly unsupported
    Given the provider descriptor does not advertise function "<function>"
    When the Endpoint requests "<function>"
    Then the result is unsupported
    And no other provider function is used as a substitute

    Examples:
      | function       |
      | query_command  |
      | read_output    |
      | follow_output  |
      | watch          |

  Scenario: Describe is available through the bootstrap contract
    Given no provider descriptor has been accepted yet
    When the Endpoint invokes describe with the fixed bootstrap envelope
    Then the provider can describe protocol versions, functions, queries, operations, and constraints
    And describe does not depend on a capability learned from itself

  Scenario: Discovery is bounded and reports completeness
    Given the provider advertises discover
    When the Endpoint invokes discovery with record, byte, and deadline budgets
    Then the result stays within every accepted budget
    And the result states whether discovery is complete
    And an incomplete result is not treated as a complete empty inventory

  Scenario: Inspect separates existence from liveness
    Given a provider resource record exists without a verified live process
    When the Endpoint invokes inspect
    Then the result reports the record as found
    And it reports liveness as unverified or not live
    And it does not invent a generation

  Scenario: Execute is reserved for standard mutations
    Given the Cluster defines a mutating operation and payload schema
    When the Endpoint invokes execute
    Then the provider applies only that standard operation
    And provider-native arbitrary command strings are not accepted

  Scenario: Query is reserved for Cluster-registered reads
    Given the Cluster defines a read-only query and result schema
    When the Endpoint invokes query
    Then no provider state is mutated
    And no provider-defined query namespace is accepted

  Scenario: Query command cannot create a missing correlation record
    Given the provider has no record for an invocation ID
    When the Endpoint invokes query_command
    Then the provider returns a standard not_found or unsupported result
    And it does not execute the original mutation

  Scenario: Read output is a snapshot rather than a stream
    Given the provider supports read_output
    When the Endpoint invokes read_output
    Then exactly one bounded snapshot result is returned
    And no live-follow guarantee is implied

  Scenario: Follow output is a stream rather than repeated snapshots
    Given the provider supports follow_output
    When the Endpoint invokes follow_output
    Then one provider stream remains active until terminal outcome or cancellation
    And the provider does not simulate follow by returning a single snapshot

  Scenario: Watch emits typed events under a bounded checkpoint contract
    Given the provider supports watch
    When the Endpoint starts watch from an accepted checkpoint
    Then emitted events use Cluster-defined event schemas
    And every event is bounded and correlated to the watch request
    And an expired checkpoint returns an explicit gap or resynchronization outcome

  Scenario: Cancellation of watch releases only watch resources
    Given a provider watch is active
    When the Endpoint cancels that watch
    Then the provider watch invocation and its helpers exit
    And discovered Agents and Sessions remain unchanged
