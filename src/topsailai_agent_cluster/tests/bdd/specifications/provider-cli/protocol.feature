Feature: Provider CLI protocol framing and compatibility
  The Endpoint invokes a locally configured provider executable through one
  versioned language-neutral protocol. A malformed or incompatible provider must
  fail at the seam without being mistaken for a successful business operation.

  Background:
    Given an Endpoint with a locally configured provider CLI
    And the provider executable is trusted local configuration
    And the provider process is started without a shell

  Scenario: A compatible non-streaming request returns one correlated document
    Given the provider supports Adapter CLI protocol major 1
    When the Endpoint sends one versioned JSON request with request ID "request-1"
    Then stdout contains exactly one JSON response document
    And the response uses request ID "request-1"
    And the response uses the negotiated protocol version
    And the provider process exit status and protocol result are recorded separately

  Scenario: Bootstrap describe negotiates without a prior provider descriptor
    Given the Endpoint knows only the fixed protocol bootstrap envelope
    When the Endpoint invokes the describe function
    Then the provider returns its supported protocol range in the bootstrap response
    And the Endpoint selects only a mutually supported version
    And no provider capability is admitted before version compatibility is established

  Scenario: An incompatible major version is rejected before a business request
    Given the provider supports only Adapter CLI protocol major 2
    And the Endpoint supports only Adapter CLI protocol major 1
    When the Endpoint invokes the describe function
    Then the Adapter instance is marked incompatible
    And no discover, query, execute, or output function is invoked
    And no mutating capability is published

  Scenario: An unknown minor feature is used only after negotiation
    Given the provider and Endpoint share protocol major 1
    And only the provider advertises minor feature "future-frame"
    When the Endpoint negotiates the Adapter instance
    Then the Endpoint does not send "future-frame"
    And functions supported by the common feature set remain available

  Scenario: Empty stdout is a protocol failure
    Given the provider exits without writing a response
    When the Endpoint invokes a non-streaming provider function
    Then the invocation fails with a protocol error
    And it is not reported as a provider business rejection
    And a mutating invocation keeps unknown effect unless non-application is proven

  Scenario: A banner before the JSON response is rejected
    Given the provider writes a human-readable banner to stdout before its response
    When the Endpoint invokes a non-streaming provider function
    Then the invocation fails with a protocol error
    And the banner is not parsed as provider evidence

  Scenario: Multiple JSON responses are rejected for one non-streaming request
    Given the provider writes two JSON response documents to stdout
    When the Endpoint invokes a non-streaming provider function
    Then the invocation fails with a protocol error
    And neither document is accepted as the authoritative result

  Scenario: A mismatched request ID is rejected
    Given the Endpoint sends request ID "request-1"
    And the provider returns request ID "request-2"
    When the response is validated
    Then the invocation fails with a correlation error
    And the response cannot complete another pending request

  Scenario: Provider logs are isolated from protocol output
    Given the provider writes bounded diagnostics to stderr
    And the provider writes one valid response to stdout
    When the Endpoint invokes the provider
    Then the response is parsed only from stdout
    And stderr is retained only as bounded diagnostic evidence
    And stderr text does not change the response semantics

  Scenario: Oversized stdout fails visibly
    Given the provider response exceeds the Endpoint stdout byte budget
    When the Endpoint reads the response
    Then the invocation fails with an output limit error
    And the shortened data is not parsed as a complete response
    And the exact provider process group owned by the invocation is cleaned up

  Scenario: Oversized stderr is truncated without corrupting a valid response
    Given the provider writes diagnostics beyond the stderr byte budget
    And the provider writes one valid bounded response to stdout
    When the Endpoint invokes the provider
    Then the protocol response is handled normally
    And stderr is retained only up to its configured bound
    And diagnostic truncation is labelled

  Scenario: A transport failure and a provider rejection remain different
    Given one provider invocation cannot produce a valid protocol response
    And another invocation returns a standard provider rejection
    When the Endpoint records both outcomes
    Then the first outcome is classified as a process or protocol failure
    And the second outcome preserves the provider error code and evidence
    And the two outcomes do not share the same effect certainty by default
