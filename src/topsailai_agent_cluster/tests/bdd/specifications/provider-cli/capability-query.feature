Feature: Effective capabilities and standard provider queries
  The provider describes what it can implement, but the Endpoint publishes only
  the intersection of provider support, Cluster standards, and local policy.
  Read-only provider surfaces use one Cluster-defined query framing.

  Background:
    Given an Endpoint with a compatible provider binding
    And the Cluster has a versioned operation and query registry

  Scenario: Effective capabilities are the approved intersection
    Given the provider describes operations "message.send" and "agent.stop"
    And the Cluster registry recognizes both operations
    And Endpoint policy approves only "message.send"
    When the Endpoint computes effective capabilities
    Then only "message.send" is published
    And the effective capability revision includes the provider descriptor and policy revision

  Scenario: A provider cannot advertise an unknown standard operation
    Given the provider describes operation "provider.private.restart"
    And the Cluster registry does not define that operation
    When the Endpoint validates the descriptor
    Then the unknown operation is excluded from effective capabilities
    And it cannot be submitted as a standard operation

  Scenario: Query and mutation capabilities remain separate
    Given the provider supports query "model.catalog"
    And the provider supports operation "agent.model.select"
    When the Endpoint publishes effective capabilities
    Then "model.catalog" appears only in query capabilities
    And "agent.model.select" appears only in mutating operation capabilities

  Scenario Outline: A registered query is accepted with its Cluster schema
    Given the provider advertises query "<query>"
    And Endpoint policy permits the query
    When the Endpoint computes effective query capabilities
    Then query "<query>" is published with its Cluster-defined request and result schema

    Examples:
      | query             |
      | launch.options    |
      | history.messages  |
      | model.catalog     |
      | session.messages  |

  Scenario: A provider-namespaced query is rejected
    Given the provider advertises query "topsailai.internal.files"
    And the Cluster query registry does not define it
    When the Endpoint validates the descriptor
    Then the query is not published
    And a request for it returns unsupported

  Scenario: Query framing cannot mutate provider state
    Given the provider advertises query "model.catalog"
    When a query request contains a model selection mutation
    Then the request is rejected by Cluster schema validation
    And the provider query is not invoked
    And model selection remains available only through a mutating execute operation

  Scenario: An unsupported standard query is explicit
    Given the Cluster defines query "history.messages"
    And the provider does not advertise it
    When an operator requests "history.messages" for that binding
    Then the response is unsupported
    And no unrelated provider query is used as a substitute

  Scenario: Endpoint startup refreshes the provider descriptor
    Given the provider executable is configured for a binding
    When the Endpoint starts
    Then it invokes describe before admitting provider operations
    And it computes an effective capability revision from the accepted descriptor

  Scenario: Periodic discovery reuses the accepted descriptor
    Given the binding has an accepted compatible descriptor
    When several periodic discovery cycles run without a configuration event
    Then describe is not invoked for every discovery cycle
    And discovery remains constrained by the accepted effective capabilities

  Scenario Outline: A local configuration event refreshes the descriptor
    Given the binding has an accepted descriptor
    When the Endpoint processes "<event>"
    Then the Endpoint invokes describe for that binding
    And a changed effective surface produces a new effective capability revision

    Examples:
      | event                              |
      | binding configuration change       |
      | provider executable version switch |
      | provider startup configuration change |
      | Endpoint policy reload              |
      | control action approval reload      |

  Scenario: Describe failure degrades instead of publishing an empty healthy surface
    Given the binding previously had an accepted descriptor and valid inventory
    When a required descriptor refresh fails
    Then the binding becomes degraded or unavailable
    And the prior inventory remains explicitly stale
    And no healthy empty capability set is published
    And new mutating operations are refused

  Scenario: Recovery publishes a new revision before mutation resumes
    Given a binding is degraded because descriptor refresh failed
    When a compatible descriptor is accepted later
    Then the Endpoint computes and publishes a new effective capability revision
    And only then may new mutating operations be admitted

  Scenario: Provider control actions require both description and local approval
    Given the provider describes control actions "heartbeat" and "session.messages"
    And Endpoint policy approves only "heartbeat"
    When effective control capabilities are computed
    Then only "ctl.heartbeat" is published
    And no provider argv template appears in the Endpoint capability

  Scenario: A stale capability revision cannot reinterpret a command
    Given an operator prepared a command against effective capability revision "revision-1"
    And policy reload produces effective capability revision "revision-2"
    When the command is admitted after the reload
    Then admission rejects the stale capability revision
    And the command is not reinterpreted under "revision-2"
