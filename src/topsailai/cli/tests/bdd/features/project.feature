@bdd @noninteractive
Feature: Manage projects non-interactively
  Project registry commands must operate in an isolated TopsailAI home and
  must never delete the registered project directory.

  Background:
    Given an isolated TopsailAI home and working directory

  Scenario: Add an existing project
    Given an existing project directory named "alpha"
    When I add project "alpha"
    Then the command succeeds
    And project "alpha" is registered

  Scenario: Reject a duplicate project path
    Given an existing project directory named "alpha"
    And project "alpha" is already registered
    When I add project "alpha"
    Then the command fails
    And project "alpha" has exactly one registry entry

  Scenario: Delete a registry entry without deleting the project directory
    Given an existing project directory named "alpha"
    And project "alpha" is already registered
    When I delete project "alpha"
    Then the command succeeds
    And project "alpha" is not registered
    But project directory "alpha" still exists

  Scenario: Reject a project directory that does not exist
    Given a missing project directory named "missing"
    When I add project "missing"
    Then the command fails
    And project "missing" is not registered
