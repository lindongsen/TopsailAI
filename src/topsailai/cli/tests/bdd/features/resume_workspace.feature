@bdd @noninteractive
Feature: Resume a session in its persisted project workspace
  A resumed session must run in the project workspace recorded for that
  session, even when the caller never exported the workspace variable. The
  persisted record is authoritative, so a resume never falls back to the
  caller's working directory and never invents a directory.

  Background:
    Given an isolated resume home and caller directory

  Scenario: Resume launches the child in the persisted workspace
    Given a persisted session "s-resume" whose workspace is "project-alpha"
    When I resume session "s-resume"
    Then the resume succeeds
    And the launched child ran in the persisted workspace
    And the launched child received the persisted workspace variable

  Scenario: Resume restores the caller environment afterwards
    Given a persisted session "s-resume" whose workspace is "project-alpha"
    And the caller has no workspace variable
    When I resume session "s-resume"
    Then the resume succeeds
    And the caller has no workspace variable

  Scenario: Resume refuses a session without a persisted workspace
    Given a persisted session "s-blank" whose workspace is empty
    When I resume session "s-blank"
    Then the resume fails with status 4
    And no child was launched

  Scenario: Resume refuses a workspace that is not a directory
    Given a persisted session "s-gone" whose workspace is missing
    When I resume session "s-gone"
    Then the resume fails with status 4
    And no child was launched

  Scenario: Resume refuses a relative workspace
    Given a persisted session "s-relative" whose workspace is relative
    When I resume session "s-relative"
    Then the resume fails with status 4
    And no child was launched
