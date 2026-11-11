Feature: Endpoint access policy management
  The Server routes an authenticated request but never decides whether it may
  reach the provider. The Endpoint loads one local policy file per token and
  applies policy changes atomically.

  Scenario: no policy directory keeps the Endpoint permissive
    Given a real cluster with no Endpoint access policy directory
    When the policy probe reads session output
    Then the policy probe reaches the provider

  Scenario: an empty policy directory keeps the Endpoint permissive
    Given a real cluster with an empty Endpoint access policy directory
    When the policy probe reads session output
    Then the policy probe reaches the provider

  Scenario Outline: a configured policy refuses an unusable credential
    Given a real cluster whose Endpoint policy grants output read to its registered token
    And the CLI uses the <credential> Endpoint credential
    When the policy probe reads session output
    Then the policy probe is refused before provider invocation

    Examples:
      | credential |
      | missing    |
      | wrong      |
      | unlisted   |

  Scenario: an Endpoint declaration excludes a token from this Endpoint
    Given a real cluster whose token is restricted to another Endpoint
    When the policy probe reads session output
    Then the policy probe is refused before provider invocation

  Scenario: scopes and individual permissions combine by union
    Given a real cluster whose token has view scope and output read permission
    When the policy probe reads session output
    Then the policy probe reaches the provider

  Scenario: allow all admits the operation
    Given a real cluster whose token is allowed every operation
    When the policy probe reads session output
    Then the policy probe reaches the provider

  Scenario: deny all refuses the operation
    Given a real cluster whose token is denied every operation
    When the policy probe reads session output
    Then the policy probe is refused before provider invocation

  Scenario: a hashed token authenticates the matching plaintext credential
    Given a real cluster whose Endpoint policy stores a hash of the CLI token
    When the policy probe reads session output
    Then the policy probe reaches the provider

  Scenario: a successful SIGHUP reload replaces the active policy
    Given a real cluster whose policy initially denies output read
    When the policy is replaced with an output read grant and reloaded
    And the policy probe reads session output
    Then the policy probe reaches the provider

  Scenario: a malformed SIGHUP reload keeps the previous policy
    Given a real cluster whose policy initially grants output read
    When the policy is replaced with a malformed rule and reload is attempted
    And the policy probe reads session output
    Then the policy probe reaches the provider
