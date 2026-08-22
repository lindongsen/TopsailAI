@bdd @noninteractive
Feature: Manage models non-interactively
  Model registry commands must preserve configuration, reject secrets, and
  operate only in an isolated TopsailAI home.

  Background:
    Given an isolated TopsailAI home and working directory

  Scenario: Add a model using credential environment references and list it
    When I add model "Primary" with credential environment references
    Then the command succeeds
    When I list models as JSON
    Then the command succeeds
    And model "Primary" appears in the JSON output

  Scenario: Get a model as JSON
    Given model "Primary" is already configured
    When I get model "Primary" as JSON
    Then the command succeeds
    And the JSON output contains the complete configuration for model "Primary"

  Scenario: Update a model while preserving existing configuration
    Given model "Primary" is already configured
    When I update model "Primary" with a new base URL
    Then the command succeeds
    When I get model "Primary" as JSON
    Then the JSON output contains the updated base URL
    And the JSON output preserves the credential environment references

  Scenario: Reject a duplicate model name
    Given model "Primary" is already configured
    When I add model "Primary" with credential environment references
    Then the command fails
    And model "Primary" has exactly one registry entry

  Scenario: Reject a literal secret field
    When I add model "Unsafe" with a literal API key
    Then the command fails
    And model "Unsafe" is not in the registry

  Scenario: Delete one model without affecting another model
    Given model "Primary" is already configured
    And model "Secondary" is already configured
    When I delete model "Primary" without confirmation
    Then the command succeeds
    And model "Primary" is not in the registry
    But model "Secondary" is in the registry
