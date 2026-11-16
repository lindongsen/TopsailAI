Feature: A broken policy stops the Node
  The policy file is the only place a scope is defined and a permission granted,
  so a problem with it is a startup failure. A Node that started with a broken
  policy would be a Node whose operator believes a grant exists that does not.

  One case is deliberately not a failure: a scope whose directory does not exist.
  The scope stays defined and refuses every request, because a policy may name a
  directory that has not been created yet and one absent directory must not stop a
  Node that serves several. The Node still refuses to start when the policy itself
  is wrong, which is what the other scenarios here assert.

  Scenario: A missing policy file stops the Node
    Given a policy file that does not exist
    When the node loads the policy
    Then the node refuses to start

  Scenario: An unknown version stops the Node
    Given a policy with an unknown version
    When the node loads the policy
    Then the node refuses to start
    And the refusal names "not supported"

  Scenario: A malformed document stops the Node
    Given a policy that is not valid YAML
    When the node loads the policy
    Then the node refuses to start

  Scenario: A scope pointing at a missing directory starts and refuses every request
    Given a policy whose scope "project" points at a missing directory
    When the node loads the policy
    Then the node starts
    When the caller reads "notes.txt" on scope "project"
    Then the caller receives the code "not_found"

  Scenario: A scope pointing at a file stops the Node
    Given a policy whose scope "project" points at a file
    When the node loads the policy
    Then the node refuses to start

  Scenario: A policy with no scope starts and serves nothing
    Given a policy that defines no scope
    When the node loads the policy
    Then the node starts
