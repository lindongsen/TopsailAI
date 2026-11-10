Feature: A broken policy stops the Node
  The policy file is the only place a scope is defined and a permission granted,
  so every problem with it is a startup failure. A Node that started with a broken
  policy would be a Node whose operator believes a grant exists that does not.

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

  Scenario: A scope pointing at a missing directory stops the Node
    Given a policy whose scope "project" points at a missing directory
    When the node loads the policy
    Then the node refuses to start

  Scenario: A scope pointing at a file stops the Node
    Given a policy whose scope "project" points at a file
    When the node loads the policy
    Then the node refuses to start

  Scenario: A policy with no scope starts and serves nothing
    Given a policy that defines no scope
    When the node loads the policy
    Then the node starts
