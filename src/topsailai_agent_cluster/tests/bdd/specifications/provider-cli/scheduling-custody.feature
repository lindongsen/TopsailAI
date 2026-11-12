Feature: Adapter instance scheduling and provider process custody
  Every configured Adapter instance has independent bounded capacity. The Generic CLI
  Adapter owns invocation helpers, while a provider business resource may outlive
  the call only after a durable independent custody handoff.

  Background:
    Given an Endpoint with configured Adapter instances "adapter-a" and "adapter-b"
    And each Adapter instance has an independent bounded scheduler

  Scenario: Effective capacity uses the strictest total limit
    Given the Endpoint hard total limit is 8
    And Adapter instance "adapter-a" has a local total limit of 6
    And its provider describes a total limit of 4
    When the Endpoint computes Adapter instance "adapter-a" capacity
    Then the effective total limit is 4

  Scenario: Provider limits cannot expand Endpoint hard limits
    Given the Endpoint hard mutation limit is 2
    And the provider describes a mutation limit of 20
    When the Endpoint computes mutation capacity
    Then the effective mutation limit is 2

  Scenario: An Adapter-local limit can further narrow provider capacity
    Given the Endpoint hard discovery limit is 4
    And the provider describes a discovery limit of 4
    And Adapter instance "adapter-a" has a local discovery limit of 1
    When two discovery requests reach Adapter instance "adapter-a"
    Then at most one discovery invocation runs at a time

  Scenario: A blocked provider does not consume another Adapter instance's capacity
    Given all total slots for Adapter instance "adapter-a" are occupied by blocked invocations
    And Adapter instance "adapter-b" has available capacity
    When a request reaches Adapter instance "adapter-b"
    Then Adapter instance "adapter-b" starts its provider invocation
    And it does not wait for a slot from Adapter instance "adapter-a"

  Scenario: Discovery serializes with mutation when required
    Given Adapter instance "adapter-a" describes that discovery serializes with mutation
    And a mutation invocation is active for Adapter instance "adapter-a"
    When discovery is requested for Adapter instance "adapter-a"
    Then discovery does not run concurrently with that mutation
    And the request is bounded by the configured queue policy

  Scenario: Discovery may overlap mutation when explicitly supported
    Given Adapter instance "adapter-a" describes that discovery need not serialize with mutation
    And separate discovery and mutation slots are available
    When discovery and mutation are requested concurrently
    Then both invocations may run within the total limit

  Scenario: A full scheduler fails visibly instead of growing forever
    Given Adapter instance "adapter-a" has exhausted running and queued capacity
    When another provider invocation is requested
    Then admission fails with a capacity error
    And no additional provider process is started
    And no unbounded waiting item is retained

  Scenario: Invocation helper exits with a successful non-durable call
    Given a provider invocation creates a helper process owned by that call
    When the provider function finishes
    Then the helper exits before invocation cleanup completes
    And no helper process remains after the request

  Scenario: Cancellation cleans the exact invocation process group
    Given a provider invocation and its helper are active
    When the invocation is cancelled before custody handoff
    Then the Generic CLI Adapter terminates only the exact owned process group
    And no process is terminated by a broad name match
    And effect certainty remains unknown when application cannot be disproved

  Scenario: A durable Agent survives provider CLI exit after handoff
    Given a provider start invocation creates an Agent
    And the provider completes a durable independent custody handoff
    When the provider CLI exits successfully
    Then the Agent remains alive outside the invocation process group
    And the provider may report acknowledged effect

  Scenario: A provider cannot acknowledge before custody handoff
    Given a provider start invocation creates an Agent
    But durable independent custody handoff is not complete
    When the provider CLI prepares its result
    Then it must not report acknowledged effect
    And the result reports unknown effect or a proven non-application outcome

  Scenario: Timeout before custody handoff cleans helpers without claiming success
    Given a provider start invocation times out before custody handoff completes
    When the Generic CLI Adapter enforces the deadline
    Then invocation helpers in the owned process group are cleaned up
    And the Endpoint records unknown effect unless non-application is proven
    And the command is not automatically retried

  Scenario: Later cleanup does not kill a handed-off Agent
    Given a previous invocation completed durable custody handoff for an Agent
    And another invocation for the same Adapter instance later times out
    When the later invocation process group is cleaned up
    Then the previously handed-off Agent remains alive
