Feature: Provider resource identity and discovery
  Provider resources keep private keys at the provider seam while the Endpoint
  alone mints public Cluster IDs. Identity remains stable across collection,
  restart, and compatible provider upgrades.

  Background:
    Given a configured provider binding with ID "binding-a"
    And the Endpoint owns the ResourceMapper

  Scenario: Discovery maps a provider Session to a Cluster resource
    Given discovery returns a Session with provider key "resource-1"
    And discovery returns provider generation "generation-1"
    When the Endpoint accepts the observation
    Then the Endpoint maps the tuple "binding-a", "session", "resource-1"
    And the published Session has a stable opaque Cluster resource ID
    And the provider response contains no Cluster resource ID authority

  Scenario: Repeated discovery reuses the same Cluster resource ID
    Given a Session observation with provider key "resource-1" was mapped previously
    When the same binding discovers the same Session again
    Then the existing Cluster resource ID is reused
    And no second mapping is created

  Scenario: Equal provider keys for different resource kinds remain distinct
    Given discovery returns a Session with provider key "resource-1"
    And discovery returns a Task with provider key "resource-1"
    When the Endpoint maps both observations
    Then the Session and Task receive different Cluster resource IDs
    And both mappings retain their resource kind

  Scenario: Equal provider keys in different bindings remain distinct
    Given binding "binding-a" discovers Session key "resource-1"
    And binding "binding-b" discovers Session key "resource-1"
    When the Endpoint maps both observations
    Then the two Sessions receive different Cluster resource IDs
    And neither binding can resolve the other binding's resource

  Scenario: A provider cannot choose a public Cluster ID
    Given a provider observation includes a field claiming Cluster ID "res-forged"
    When the Endpoint validates the observation
    Then the observation is rejected as a protocol violation
    And "res-forged" is not persisted in ResourceMapper

  Scenario: Reverse lookup sends only provider authority across the seam
    Given Cluster Session "res-session" maps to provider key "resource-1"
    When the Endpoint prepares a provider request for that Session
    Then the provider target contains provider key "resource-1"
    And the provider target contains the expected provider generation
    And the provider target does not contain Cluster Session "res-session"

  Scenario: A successful empty discovery clears only that binding's resources
    Given binding "binding-a" previously reported Sessions
    And binding "binding-b" previously reported Sessions
    When binding "binding-a" returns a successful complete empty discovery
    Then binding "binding-a" publishes an empty resource section
    And binding "binding-b" keeps its existing observations

  Scenario: A failed discovery does not become a successful empty inventory
    Given binding "binding-a" previously reported a Session
    When its provider discovery fails before a complete result
    Then the last valid Session remains present and stale
    And the binding reports its collection error
    And the failure is not published as a successful empty discovery

  Scenario: Compatible provider restart preserves identity
    Given provider version "1.0.0" discovered Session key "resource-1"
    When the same provider version restarts and discovers the same business Session
    Then it returns provider key "resource-1"
    And the Endpoint reuses the prior Cluster resource ID

  Scenario: Compatible provider upgrade preserves identity
    Given provider version "1.0.0" discovered Session key "resource-1"
    And provider version "1.1.0" claims identity compatibility
    When version "1.1.0" discovers the same business Session
    Then it returns provider key "resource-1"
    And upgrade acceptance keeps the prior Cluster resource ID

  Scenario: A silent key change blocks a compatible upgrade
    Given provider version "1.0.0" discovered Session key "resource-1"
    And provider version "1.1.0" claims identity compatibility
    But version "1.1.0" returns "renamed-resource-1" for the same business Session
    When upgrade identity checks run
    Then the provider cutover is rejected
    And the active binding remains on version "1.0.0"

  Scenario: An approved breaking identity migration uses a new binding namespace
    Given a provider cannot preserve or alias its previous resource keys
    And the operator approves a breaking identity migration
    When the new provider version is activated under binding "binding-a-v2"
    Then new resources are mapped in the "binding-a-v2" namespace
    And old mappings remain associated with "binding-a"
    And the migration is not presented as an identity-preserving upgrade

  Scenario: One binding publishes multiple launch profiles
    Given binding "binding-a" advertises provider launch profiles "default" and "large"
    When the Endpoint publishes standard launch profiles
    Then each profile receives its own opaque "launch_profile_id"
    And both launch profile IDs resolve to binding "binding-a"
    And neither public launch profile ID is required to equal the binding ID
