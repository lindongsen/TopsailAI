Feature: Independent provider packaging and safe activation
  The Endpoint package contains the Generic CLI Adapter but no concrete provider.
  Provider packages install versioned executables and become active only through
  an explicit validated local Adapter instance change.

  Scenario: Endpoint installs without a concrete provider package
    Given no concrete provider package is installed
    When the "agent-cluster-endpoint" package is installed
    Then package dependency resolution succeeds
    And the Endpoint executable is present
    And no TopsailAI provider executable is required

  Scenario: TopsailAI provider is an optional independent package
    Given the Endpoint package is already installed
    When "agent-cluster-provider-topsailai" is installed
    Then a versioned TopsailAI provider executable is installed
    And the Endpoint package contents are not replaced
    And the Endpoint is not restarted automatically

  Scenario: Mock provider is absent from default production artifacts
    Given default production packages and images have been built
    When those production artifacts are inspected
    Then no Mock provider executable is present
    And no production Adapter instance references the Mock provider

  Scenario: Provider installation does not activate the new version
    Given Adapter instance "adapter-a" uses provider version "1.0.0"
    When provider version "1.1.0" is installed
    Then Adapter instance "adapter-a" still points to version "1.0.0"
    And the effective capability revision remains unchanged

  Scenario: A compatible provider version is activated after validation
    Given provider versions "1.0.0" and "1.1.0" are installed at different immutable paths
    And Adapter instance "adapter-a" currently uses version "1.0.0"
    When version "1.1.0" passes describe compatibility, conformance, and bounded smoke checks
    And the operator atomically updates the Adapter instance to version "1.1.0"
    Then new invocations use the version "1.1.0" executable path
    And the Endpoint refreshes the descriptor
    And a new effective capability revision is published when the surface changes

  Scenario: Failed validation leaves the active provider unchanged
    Given Adapter instance "adapter-a" currently uses provider version "1.0.0"
    And provider version "1.1.0" fails protocol compatibility or conformance
    When activation is attempted
    Then Adapter instance "adapter-a" remains on version "1.0.0"
    And version "1.1.0" receives no production request

  Scenario: Rollback restores the previous immutable provider path
    Given Adapter instance "adapter-a" was switched from version "1.0.0" to "1.1.0"
    And version "1.0.0" remains installed during the acceptance window
    When cutover acceptance rejects version "1.1.0"
    Then the Adapter instance is atomically restored to version "1.0.0"
    And the Endpoint re-runs describe for version "1.0.0"
    And the restored effective capability revision is published before mutation resumes

  Scenario: An active executable is not overwritten in place
    Given Adapter instance "adapter-a" points to an immutable version "1.0.0" path
    When a newer provider package is installed
    Then it uses a different versioned executable path
    And the bytes at the active "1.0.0" path remain unchanged

  Scenario: Removing an inactive provider version does not affect the Endpoint
    Given Adapter instance "adapter-a" uses provider version "1.1.0"
    And provider version "1.0.0" is no longer retained for rollback
    When version "1.0.0" is removed
    Then the Endpoint remains installed and running
    And Adapter instance "adapter-a" continues to use version "1.1.0"

  Scenario: Removing the active provider degrades only its Adapter instance
    Given Adapter instance "adapter-a" points to one provider executable
    And another Adapter instance "adapter-b" uses a different installed provider
    When the active executable for "adapter-a" becomes unavailable
    Then "adapter-a" becomes unavailable and refuses mutation
    And "adapter-b" remains operational
    And the Endpoint process remains running
