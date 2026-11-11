---
maintainer: AI
author: DawsonLin
status: specification
---

# Feature: Endpoint access policy is the only operation authorization authority

## Background

Given the Server and required Endpoints passed the environment scenarios
And the CLI has separate Server and Endpoint credential configuration
And token secret values are hidden from transcripts and process listings
And the operator can observe whether the provider was invoked
And the policy under test belongs to the live-test Endpoint

## Scenario AUTH-LIVE-001: Missing Server credential is refused by the Server

Given the CLI has no Server credential
When it lists Endpoints
Then the Server returns `unauthorized`
And no Endpoint request is sent
And the failure is not reported as `policy_denied`

## Scenario AUTH-LIVE-002: Wrong Server credential is refused by the Server

Given the CLI has a wrong Server credential and a valid Endpoint token
When it requests a detailed operation
Then the Server returns `unauthorized`
And the Endpoint does not evaluate its policy
And the provider is not invoked

## Scenario AUTH-LIVE-003: Valid Server credential can list the fleet without an Endpoint token

Given the CLI has a valid Server credential and no Endpoint token
When it lists Endpoints and persisted session summaries
Then the fleet and session-list projections are visible
And no detailed provider read is performed
And the result proves inventory visibility is not an Endpoint-policy permission

## Scenario AUTH-LIVE-004: Absent policy configuration preserves the permissive default

Given the Endpoint has no configured access-policy directory
And the CLI has a valid Server credential
When the CLI performs one approved detailed read and one test-owned management operation
Then both operations are allowed by the Endpoint policy layer
And local capability, allowlist, and provider checks still apply
And the report labels this as the backward-compatible permissive default

## Scenario AUTH-LIVE-005: A configured policy directory refuses an unlisted token

Given the Endpoint policy directory contains at least one valid token file
And the CLI presents a different unlisted Endpoint token
When it requests `output.read`
Then the Endpoint refuses the request with `policy_denied`
And the message names `output.read`
And the provider is not invoked
And the Server does not replace the refusal with `unauthorized`, `unsupported`, or `provider_error`

## Scenario AUTH-LIVE-006: Missing Endpoint token is refused after policy is configured

Given the Endpoint policy directory is restrictive
And the CLI has a valid Server credential but no Endpoint token mapping for the target
When it requests `messages.read`
Then the request is refused
And the diagnostic identifies the missing local Endpoint-token configuration
And the authoritative remote code remains `policy_denied`
And the provider is not invoked

## Scenario AUTH-LIVE-007: Wrong Endpoint token is refused without revealing a match

Given the Endpoint policy directory is restrictive
And the CLI presents a wrong Endpoint token
When it requests a detailed operation
Then the Endpoint returns `policy_denied`
And the response does not reveal whether a similar token name or hash exists
And no token value appears in Server or Endpoint logs
And the provider is not invoked

## Scenario AUTH-LIVE-008: One token file can be limited to one Endpoint

Given the same token rule is deployed to Endpoint A and Endpoint B
And its `endpoints` declaration contains only Endpoint A
When the CLI uses that token for the same allowed operation on both Endpoints
Then Endpoint A allows the operation
And Endpoint B returns `policy_denied`
And the Server routes both requests without making the authorization decision

## Scenario AUTH-LIVE-009: Omitting endpoints grants the rule to every Endpoint holding the file

Given an otherwise restricted token file omits the `endpoints` declaration
And the identical rule is installed on Endpoint A and Endpoint B
When the CLI invokes an explicitly granted read on both
Then both Endpoints allow it
And the result is not interpreted as cross-Endpoint caller identity

## Scenario AUTH-LIVE-010: A denied token can still see inventory but cannot read details

Given a token file contains only `deny-all`
And the CLI maps that token to the target Endpoint
When the CLI lists the fleet and sessions
Then the list remains visible
When the CLI requests output, messages, history, models, or a management command
Then every detailed operation is refused with `policy_denied`
And no provider invocation occurs

## Scenario AUTH-LIVE-011: Scope grants all operations in its capability class

Given a token rule grants the `read_output` scope and no individual permissions
When the CLI requests `output.read` and `output.follow`
Then both operations are allowed
And an operation outside that scope is refused with `policy_denied`
And provider evidence exists only for the allowed reads

## Scenario AUTH-LIVE-012: One exact permission does not grant its sibling operation

Given a token rule grants only `output.read`
When the CLI reads an output snapshot
Then the snapshot operation is allowed
When the CLI starts output follow with the same token
Then `output.follow` is refused with `policy_denied`
And no follow child process is started

## Scenario AUTH-LIVE-013: Scope and individual permissions form a union

Given a token rule grants the `read_output` scope
And the same rule grants one management permission outside that scope
When the CLI performs operations covered by either declaration
Then every listed or scope-covered operation is allowed
And an unrelated operation is refused

## Scenario AUTH-LIVE-014: Read-only token cannot execute management commands

Given a token rule grants only read scopes and read permissions
When the CLI submits send, inject, interrupt, stop, drive, model selection, provider control, and exec operations
Then every submitted management operation ends with `policy_denied`
And effect certainty is `not_applied`
And no provider-side effect occurs

## Scenario AUTH-LIVE-015: Single-command token permits only its exact operation

Given a token rule grants one exact operation such as `message.send`
When the CLI sends literal text to the test session
Then that operation reaches the provider once
When the CLI uses the same token for inject or interrupt
Then those operations are refused with `policy_denied`

## Scenario AUTH-LIVE-016: allow-all permits Endpoint operations but not unsafe local execution

Given a token file contains only `allow-all`
And command execution has a separate local allowlist
When the CLI performs a supported ordinary operation
Then Endpoint access policy allows it
When the CLI requests an argv outside the command allowlist
Then local execution policy still refuses it
And `allow-all` does not become a remote shell

## Scenario AUTH-LIVE-017: deny-all overrides no operation because it must stand alone

Given a token file contains only `deny-all`
When the token is used for every supported detailed read and management operation
Then every operation is refused with `policy_denied`
And no provider invocation occurs
And inventory remains visible after Server authentication

## Scenario AUTH-LIVE-018: Hashed token rule authenticates without storing the secret

Given a token file uses `token-sha256` with the correct digest
And the policy file does not contain the clear token
When the CLI presents the corresponding secret
Then the granted operation is allowed
When the CLI presents a different secret
Then the request is refused with `policy_denied`
And evidence contains the token name or digest identifier only when safe, never the secret

## Scenario AUTH-LIVE-019: Invalid policy fails Endpoint startup

Given the Endpoint is stopped in an approved maintenance window
And the configured policy directory contains an invalid policy file
When the Endpoint is started
Then startup fails visibly
And the Endpoint does not start in permissive mode
And the error identifies the file and rule without printing the token secret

## Scenario AUTH-LIVE-020: Empty policy file is rejected

Given the configured policy directory contains an empty `.conf` file
When the Endpoint validates the policy at startup
Then startup fails
And the empty file is not interpreted as an implicit deny or allow rule

## Scenario AUTH-LIVE-021: Unknown scope is rejected at policy load

Given a token file contains an unknown scope name
When the Endpoint loads the policy directory
Then the load fails
And the previous running policy remains unchanged on reload
And no caller receives authority from the invalid rule

## Scenario AUTH-LIVE-022: Unknown permission is accepted with a warning

Given a valid token file contains one future operation name not supported by this Endpoint
When the Endpoint loads or reloads the directory
Then the policy loads successfully
And a bounded warning names the unknown permission
And supported permissions in the same rule continue to work
And the unknown operation cannot execute unless it later becomes a supported advertised operation

## Scenario AUTH-LIVE-023: Successful SIGHUP reload changes policy without restarting the Endpoint

Given the Endpoint is online with a token allowed for `output.read`
And a replacement directory removes that permission and grants `messages.read`
When the operator atomically updates the file and sends `SIGHUP` to the exact Endpoint process
Then the Endpoint stays online with the same process identity
And a new `output.read` request is refused with `policy_denied`
And a new `messages.read` request is allowed
And requests are evaluated against one complete old or new policy, never a partial mixture

## Scenario AUTH-LIVE-024: Failed SIGHUP reload keeps the previous policy

Given the running Endpoint has a verified policy
And the replacement policy contains a parse error
When the operator sends `SIGHUP` to the exact Endpoint process
Then the reload failure is logged
And the Endpoint stays online
And the previously allowed operation remains allowed
And the previously denied operation remains denied
And the Endpoint does not fall back to permissive defaults

## Scenario AUTH-LIVE-025: Adding one token does not leave unlisted callers permissive

Given the Endpoint initially has no configured policy directory
And a restrictive directory with one token file is enabled during an approved restart
When the listed token and an unrelated token request the same operation
Then the listed token follows its rule
And the unrelated token is refused with `policy_denied`

## Scenario AUTH-LIVE-026: Token rotation has an explicit overlap boundary

Given an old token is active and a new token file has been prepared
When the operator deploys the new rule, reloads every target Endpoint, updates the CLI mapping, removes the old rule, and reloads again
Then the new token works after its first verified reload
And the old token stops working after its removal reload
And no request is sent with both token secrets
And the rotation report records the overlap window without recording either secret

## Scenario AUTH-LIVE-027: Policy listing and inspection do not reveal secrets

Given the approved policy-management procedure can list and inspect token rules
When the operator lists token names, Endpoints, scopes, and permissions
Then the output omits clear token secrets
And hashed rules do not expose a reversible value
And file permissions prevent unapproved users from reading the policy directory
