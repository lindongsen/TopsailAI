Feature: Local provider trust and invocation configuration
  A provider CLI is a locally trusted component for the MVP. Process separation
  gives dependency and fault boundaries, not a sandbox against malicious local
  code. Remote requests cannot choose how the provider executable is launched.

  Background:
    Given a provider binding configured by a local administrator
    And the provider CLI is trusted local software

  Scenario: Provider trust is reported without a sandbox claim
    When the Endpoint reports the provider trust model
    Then it identifies the provider as a locally trusted component
    And it does not claim filesystem, credential, network, or OS-user isolation
    And it distinguishes process fault isolation from malicious-code containment

  Scenario: Executable selection comes only from local binding configuration
    Given binding "binding-a" has a fixed versioned provider executable
    When a remote operation targets binding "binding-a"
    Then the Generic CLI Adapter starts only the configured executable
    And the remote payload cannot replace the executable path

  Scenario: Remote input cannot inject provider argv
    Given binding "binding-a" has fixed provider base arguments
    When a remote payload contains fields resembling executable arguments
    Then those fields are rejected by the standard operation schema
    And no unconfigured argument is appended to the provider process

  Scenario: Remote input cannot replace provider working directory
    Given binding "binding-a" has an Endpoint-local provider working directory
    When a remote payload contains another working directory
    Then the requested working directory is rejected or ignored by schema
    And the provider starts in the locally configured directory

  Scenario: Remote input cannot replace provider environment
    Given the provider process receives a minimal locally configured environment
    When a remote payload contains environment variables
    Then the variables are rejected by the standard schema
    And they are not added to the provider process environment

  Scenario: Provider startup settings are isolated by binding
    Given bindings "binding-a" and "binding-b" use the same provider executable
    And each binding has different local startup configuration
    When both bindings invoke the provider concurrently
    Then each invocation receives only its own binding configuration
    And neither invocation observes the other binding's settings

  Scenario: Secrets do not cross in ordinary request JSON
    Given the provider needs a local secret to reach its business backend
    When the Endpoint invokes the provider
    Then the ordinary protocol request does not contain the secret value
    And the secret is supplied only through an approved protected local mechanism

  Scenario: Secrets are absent from response and diagnostics
    Given a provider uses a local secret
    When the provider completes or fails an invocation
    Then stdout does not contain the secret
    And retained stderr does not contain the secret
    And Cluster receipts and audit records do not contain the secret

  Scenario: Mock fault mode is local-only
    Given the Mock provider supports a local fault fixture
    When a remote request contains a field selecting that fault mode
    Then schema validation rejects the field
    And the remote request cannot activate the fault

  Scenario: Provider backend implementation remains outside the Cluster contract
    Given one conforming provider calls a business CLI
    And another conforming provider calls an HTTP service
    When both return the same standard Adapter CLI result
    Then the Endpoint handles them with the same Generic CLI Adapter
    And no Cluster protocol field identifies the backend implementation mechanism

  Scenario: Provider cannot receive Endpoint credentials as business input
    Given the Endpoint has channel and Server credentials
    When it constructs a provider request
    Then those credentials are absent from the request and provider environment
    And provider authentication to its own backend uses separate local configuration

  Scenario: Malformed trusted provider output still fails closed
    Given the locally trusted provider emits malformed JSON
    When the Generic CLI Adapter validates the response
    Then the invocation fails with a protocol error
    And local trust does not bypass framing, size, or schema validation
