@bdd @noninteractive
Feature: Read CLI documentation non-interactively

  Background:
    Given an isolated TopsailAI home and working directory

  Scenario: List usage documentation
    When I list documentation
    Then the command succeeds
    And the documentation list contains "usage/topsailai.md"

  Scenario: Read a known usage document
    When I read documentation "usage/topsailai.md"
    Then the command succeeds
    And the documentation output contains "# topsailai"
    And the documentation output contains "## Purpose"

  Scenario: Reject a missing documentation file
    When I read documentation "usage/missing-document.md"
    Then the command fails
    And the documentation error identifies "usage/missing-document.md"

  Scenario: Reject documentation path traversal
    When I read documentation "../README.md"
    Then the command fails
    And the documentation error identifies "../README.md"
